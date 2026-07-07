"""Department dispatch: the swap seam for real municipal APIs later.

``DepartmentDispatcher`` mirrors the ``Geocoder`` Protocol in geocoding.py —
callers depend on the Protocol, not the concrete implementation, so swapping
``MockApiDispatcher``/``SmtpDispatcher`` for a real municipal integration later
is a one-line change in ``get_dispatcher``. ``MockApiDispatcher`` posts to the
``mock_router`` defined at the bottom of this file — a stand-in for the real
per-department systems this project will integrate with later.
"""

import asyncio
import logging
import smtplib
import uuid
from email.message import EmailMessage
from typing import Protocol

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from jan_setu.config import Settings
from jan_setu.pipeline.taxonomy import Department

logger = logging.getLogger(__name__)


class DispatchError(RuntimeError):
    pass


class DepartmentDispatcher(Protocol):
    async def dispatch(
        self, *, human_id: str, department: Department, summary: str, pdf_bytes: bytes
    ) -> str:
        """Submit the complaint to the department; return a dispatch reference."""
        ...


class MockApiDispatcher:
    """Demo stand-in for a real municipal API. Posts to our own mock endpoint
    (mock_municipal.py) so the whole flow is demoable with no external system."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http_client = http_client

    async def dispatch(
        self, *, human_id: str, department: Department, summary: str, pdf_bytes: bytes
    ) -> str:
        url = f"{self.settings.mock_api_base_url.rstrip('/')}/mock/municipal/{department.key}/complaints"
        try:
            response = await self.http_client.post(
                url, json={"human_id": human_id, "summary": summary}, timeout=10.0
            )
            response.raise_for_status()
            return response.json()["ref"]
        except (httpx.HTTPError, KeyError) as exc:
            raise DispatchError(str(exc)) from exc


class SmtpDispatcher:
    """Demo stand-in that emails the department (MailHog in dev). stdlib
    ``smtplib`` in a thread — no new async-SMTP dependency for one email."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def dispatch(
        self, *, human_id: str, department: Department, summary: str, pdf_bytes: bytes
    ) -> str:
        message = EmailMessage()
        message["Subject"] = f"Jan Setu complaint {human_id} - {department.name}"
        message["From"] = self.settings.smtp_from
        message["To"] = department.email
        message.set_content(summary)
        message.add_attachment(
            pdf_bytes, maintype="application", subtype="pdf", filename=f"{human_id}.pdf"
        )
        ref = f"MAIL-{uuid.uuid4().hex[:8]}"
        try:
            await asyncio.to_thread(self._send, message)
        except OSError as exc:
            raise DispatchError(str(exc)) from exc
        return ref

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
            smtp.send_message(message)


def get_dispatcher(settings: Settings, http_client: httpx.AsyncClient) -> DepartmentDispatcher:
    if settings.dispatcher == "smtp":
        return SmtpDispatcher(settings)
    return MockApiDispatcher(settings, http_client)


# --- Mock municipal-department API -------------------------------------------
# Accepts any complaint and returns a fake reference id, so the dispatch flow
# is demoable end to end without a real per-department integration. Mounted in
# app.py alongside the other routers.

mock_router = APIRouter()


class MockComplaintRequest(BaseModel):
    human_id: str
    summary: str


class MockComplaintResponse(BaseModel):
    ref: str


@mock_router.post(
    "/mock/municipal/{department_key}/complaints", response_model=MockComplaintResponse
)
async def submit_mock_complaint(
    department_key: str, request: MockComplaintRequest
) -> MockComplaintResponse:
    return MockComplaintResponse(ref=f"MUN-{uuid.uuid4().hex[:8]}")
