"""Google Sheets integration for application tracking."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_NAME = "Job Applications"
HEADERS = [
    "Job ID",
    "Company",
    "Role",
    "Score",
    "URL",
    "Status",
    "Applied Date",
    "Resume Path",
    "Cover Letter Path",
    "Missing Skills",
    "Strengths",
    "Notes",
    "Last Updated",
]


def _get_service():
    """Build and return the Google Sheets API service."""
    service_account_path = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON", "config/service_account.json"
    )
    service_account_path = Path(service_account_path)

    if not service_account_path.exists():
        raise FileNotFoundError(
            f"Service account file not found: {service_account_path}\n"
            "Set GOOGLE_SERVICE_ACCOUNT_JSON in your .env file."
        )

    creds = service_account.Credentials.from_service_account_file(
        str(service_account_path), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def create_or_open_tracker(spreadsheet_id: str | None = None) -> str:
    """
    Open an existing spreadsheet or create a new one.
    Returns the spreadsheet ID.
    Ensures the 'Job Applications' sheet tab exists with headers.
    """
    service = _get_service()
    sheets = service.spreadsheets()

    if not spreadsheet_id:
        # Create a new spreadsheet
        body = {
            "properties": {"title": "Job Application Tracker"},
            "sheets": [{"properties": {"title": SHEET_NAME}}],
        }
        result = sheets.create(body=body).execute()
        spreadsheet_id = result["spreadsheetId"]
        print(f"Created new spreadsheet: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")

        # Write headers
        _write_headers(service, spreadsheet_id)
    else:
        # Verify the sheet tab exists; create it if not
        meta = sheets.get(spreadsheetId=spreadsheet_id).execute()
        existing_sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]

        if SHEET_NAME not in existing_sheets:
            # Add the sheet tab
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {"title": SHEET_NAME}
                            }
                        }
                    ]
                },
            ).execute()
            _write_headers(service, spreadsheet_id)

    return spreadsheet_id


def _write_headers(service, spreadsheet_id: str) -> None:
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": [HEADERS]},
    ).execute()


def _get_existing_rows(service, spreadsheet_id: str) -> list[list[str]]:
    """Return all data rows (excluding header) from the sheet."""
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{SHEET_NAME}!A2:Z")
            .execute()
        )
        return result.get("values", [])
    except HttpError:
        return []


def sync_application(
    job_data: dict[str, Any],
    spreadsheet_id: str | None = None,
) -> None:
    """
    Upsert a job/application row in the tracker sheet.
    Matches by Job ID (column A). Updates existing row or appends new.
    """
    if spreadsheet_id is None:
        spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID", "")

    if not spreadsheet_id:
        raise ValueError(
            "No GOOGLE_SHEET_ID set. Run 'create_or_open_tracker' first and save the ID."
        )

    service = _get_service()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    missing_skills = job_data.get("missing_skills", "[]")
    if isinstance(missing_skills, str):
        try:
            missing_skills = json.loads(missing_skills)
        except json.JSONDecodeError:
            missing_skills = []

    strengths = job_data.get("strengths", "[]")
    if isinstance(strengths, str):
        try:
            strengths = json.loads(strengths)
        except json.JSONDecodeError:
            strengths = []

    row_values = [
        str(job_data.get("id", "")),
        job_data.get("company", ""),
        job_data.get("title", ""),
        str(job_data.get("score", "")),
        job_data.get("url", ""),
        job_data.get("status", ""),
        job_data.get("submitted_at", job_data.get("app_created_at", "")) or "",
        job_data.get("resume_path", "") or "",
        job_data.get("cover_letter_path", "") or "",
        ", ".join(missing_skills) if isinstance(missing_skills, list) else str(missing_skills),
        ", ".join(strengths) if isinstance(strengths, list) else str(strengths),
        job_data.get("notes", "") or "",
        now,
    ]

    existing_rows = _get_existing_rows(service, spreadsheet_id)

    job_id_str = str(job_data.get("id", ""))
    target_row_idx = None

    for i, row in enumerate(existing_rows):
        if row and row[0] == job_id_str:
            target_row_idx = i + 2  # +1 for header, +1 for 1-based index
            break

    if target_row_idx is not None:
        # Update existing row
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_NAME}!A{target_row_idx}",
            valueInputOption="RAW",
            body={"values": [row_values]},
        ).execute()
    else:
        # Append new row
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_values]},
        ).execute()


def sync_all_applications(jobs: list[dict[str, Any]], spreadsheet_id: str | None = None) -> None:
    """Sync a list of job records to the sheet."""
    if spreadsheet_id is None:
        spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID", "")

    spreadsheet_id = create_or_open_tracker(spreadsheet_id or None)

    for job in jobs:
        sync_application(job, spreadsheet_id=spreadsheet_id)
