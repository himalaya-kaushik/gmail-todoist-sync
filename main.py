#!/usr/bin/env python3
"""
Gmail-to-Todoist Sync

Fetches unread Gmail messages with .ics calendar invite attachments,
extracts meeting details, creates Todoist tasks, and marks emails as read.
Designed to run headlessly on GitHub Actions via cron.
"""

import base64
import json
import logging
import os
import re
import traceback
import uuid
from datetime import datetime, timezone

import requests
from dateutil import parser as dateutil_parser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from icalendar import Calendar

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
GMAIL_QUERY = "newer_than:1d is:unread has:attachment filename:invite.ics"
TODOIST_API_URL = "https://api.todoist.com/api/v1/tasks"
MEETING_LINK_PATTERN = re.compile(
    r"https?://(?:meet\.google\.com|[\w.-]*zoom\.us)/\S+", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def get_gmail_service():
    """Build and return an authenticated Gmail API service.

    Uses two environment variables:
        GOOGLE_CREDENTIALS_JSON – OAuth2 client secret JSON (string)
        GOOGLE_TOKEN_JSON       – pre-authorised user token JSON (with refresh_token)

    Silently refreshes expired tokens without any browser interaction.
    """
    creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    token_json = os.environ["GOOGLE_TOKEN_JSON"]

    token_data = json.loads(token_json)
    creds_data = json.loads(creds_json)

    # Extract client_id / client_secret from the nested "installed" or "web" key.
    client_info = creds_data.get("installed") or creds_data.get("web") or creds_data

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=client_info.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_info["client_id"],
        client_secret=client_info["client_secret"],
        scopes=GMAIL_SCOPES,
    )

    if creds.expired or not creds.valid:
        logger.info("Access token expired — refreshing silently …")
        creds.refresh(Request())
        logger.info("Token refreshed successfully.")

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    logger.info("Gmail service built successfully.")
    return service


def get_unread_invite_emails(service):
    """Return a list of message stubs matching the invite search query."""
    try:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=GMAIL_QUERY)
            .execute()
        )
        messages = response.get("messages", [])
        logger.info("Found %d unread invite email(s).", len(messages))
        return messages
    except Exception:
        logger.error("Failed to search Gmail:\n%s", traceback.format_exc())
        return []


# ---------------------------------------------------------------------------
# ICS / meeting detail extraction
# ---------------------------------------------------------------------------

def parse_ics(ics_bytes: bytes) -> dict:
    """Parse an .ics attachment and return {title, start_time, link}."""
    result = {"title": None, "start_time": None, "link": None}

    try:
        cal = Calendar.from_ical(ics_bytes)
        for component in cal.walk():
            if component.name == "VEVENT":
                result["title"] = str(component.get("SUMMARY", ""))

                dtstart = component.get("DTSTART")
                if dtstart:
                    dt = dtstart.dt
                    if isinstance(dt, datetime):
                        result["start_time"] = dt.astimezone(timezone.utc).strftime(
                            "%Y-%m-%d %H:%M UTC"
                        )
                    else:
                        result["start_time"] = dt.isoformat()

                # Try URL first, then LOCATION
                url = str(component.get("URL", ""))
                location = str(component.get("LOCATION", ""))
                for candidate in (url, location):
                    match = MEETING_LINK_PATTERN.search(candidate)
                    if match:
                        result["link"] = match.group(0)
                        break

                # Only process the first VEVENT
                break
    except Exception:
        logger.error("Failed to parse .ics:\n%s", traceback.format_exc())

    return result


def _extract_link_from_text(text: str) -> str | None:
    """Regex-scan plain text or HTML for a meeting link."""
    match = MEETING_LINK_PATTERN.search(text)
    return match.group(0) if match else None


def extract_meeting_details(message_stub: dict, service) -> dict:
    """Fetch the full message and return {title, start_time, link, message_id}."""
    msg_id = message_stub["id"]
    details = {"title": None, "start_time": None, "link": None, "message_id": msg_id}

    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
    except Exception:
        logger.error("Failed to fetch message %s:\n%s", msg_id, traceback.format_exc())
        return details

    payload = msg.get("payload", {})

    # --- Walk MIME parts looking for invite.ics ---
    parts_to_check = [payload] + payload.get("parts", [])
    # Handle nested multipart
    for part in list(parts_to_check):
        parts_to_check.extend(part.get("parts", []))

    ics_bytes = None
    body_text = ""

    for part in parts_to_check:
        mime = part.get("mimeType", "")
        filename = part.get("filename", "")
        body_data = part.get("body", {})

        # Collect plain/html body for fallback link extraction
        if mime in ("text/plain", "text/html"):
            data = body_data.get("data")
            if data:
                body_text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Detect .ics attachment
        if filename.lower().endswith(".ics") or mime == "text/calendar":
            att_id = body_data.get("attachmentId")
            data = body_data.get("data")

            if att_id:
                try:
                    att = (
                        service.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=msg_id, id=att_id)
                        .execute()
                    )
                    ics_bytes = base64.urlsafe_b64decode(att["data"])
                except Exception:
                    logger.error(
                        "Failed to download attachment for %s:\n%s",
                        msg_id,
                        traceback.format_exc(),
                    )
            elif data:
                ics_bytes = base64.urlsafe_b64decode(data)

    # --- Parse .ics if found ---
    if ics_bytes:
        parsed = parse_ics(ics_bytes)
        details["title"] = parsed.get("title")
        details["start_time"] = parsed.get("start_time")
        details["link"] = parsed.get("link")

    # --- Fallback: regex scan body for meeting link ---
    if not details["link"] and body_text:
        details["link"] = _extract_link_from_text(body_text)

    # --- Fallback title from email subject ---
    if not details["title"]:
        headers = payload.get("headers", [])
        for h in headers:
            if h["name"].lower() == "subject":
                details["title"] = h["value"]
                break

    details.setdefault("title", "Untitled Meeting")
    details.setdefault("start_time", "Unknown time")

    return details


# ---------------------------------------------------------------------------
# Todoist
# ---------------------------------------------------------------------------

def create_todoist_task(title: str, start_time: str, link: str | None) -> bool:
    """Create a Todoist task via the REST API v2. Returns True on success."""
    api_key = os.environ["TODOIST_API_KEY"]
    description = f"{link or 'No link found'}\nStarts: {start_time}"

    payload = {
        "content": f"Meeting: {title}",
        "due_string": "today",
        "description": description,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Request-Id": str(uuid.uuid4()),
    }

    try:
        resp = requests.post(TODOIST_API_URL, json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            logger.info("Todoist task created: %s @ %s", title, start_time)
            return True
        else:
            logger.error(
                "Todoist returned HTTP %d: %s", resp.status_code, resp.text
            )
            return False
    except Exception:
        logger.error("Failed to create Todoist task:\n%s", traceback.format_exc())
        return False


# ---------------------------------------------------------------------------
# Mark-as-read
# ---------------------------------------------------------------------------

def mark_as_read(service, message_id: str) -> None:
    """Remove the UNREAD label from a Gmail message."""
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        logger.info("Marked message %s as read.", message_id)
    except Exception:
        logger.error(
            "Failed to mark message %s as read:\n%s",
            message_id,
            traceback.format_exc(),
        )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point — fetch invites, create tasks, mark read."""
    logger.info("=== Gmail → Todoist sync starting ===")

    service = get_gmail_service()
    messages = get_unread_invite_emails(service)

    if not messages:
        logger.info("No unread invite emails found. Exiting.")
        return

    for msg_stub in messages:
        try:
            details = extract_meeting_details(msg_stub, service)
            title = details["title"]
            start_time = details["start_time"]
            link = details["link"]
            msg_id = details["message_id"]

            logger.info("Processing: '%s' at %s", title, start_time)

            success = create_todoist_task(title, start_time, link)

            if success:
                mark_as_read(service, msg_id)
            else:
                logger.warning(
                    "Skipping mark-as-read for %s — Todoist task creation failed.",
                    msg_id,
                )
        except Exception:
            logger.error(
                "Unexpected error processing message %s:\n%s",
                msg_stub.get("id", "???"),
                traceback.format_exc(),
            )

    logger.info("=== Sync complete ===")


if __name__ == "__main__":
    main()
