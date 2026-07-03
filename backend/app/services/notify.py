"""Email notifications (job completion / failure) over SMTP or SES-SMTP."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import settings


def _send(to: str, subject: str, html: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)


def _job_url(public_id: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/jobs/{public_id}"


def send_job_succeeded(to: str, kit_code: str, public_id: str) -> None:
    url = _job_url(public_id)
    subject = f"[{settings.app_name}] Job {kit_code} finished"
    text = (
        f"Your genotyping job for kit {kit_code} has completed successfully.\n\n"
        f"View results: {url}\n"
    )
    html = (
        f"<p>Your genotyping job for kit <b>{kit_code}</b> has completed successfully.</p>"
        f'<p><a href="{url}">View and download results</a></p>'
    )
    _send(to, subject, html, text)


def send_job_failed(to: str, kit_code: str, public_id: str, error: str) -> None:
    url = _job_url(public_id)
    subject = f"[{settings.app_name}] Job {kit_code} failed"
    text = (
        f"Your genotyping job for kit {kit_code} failed.\n\n"
        f"Error: {error}\n\nDetails: {url}\n"
    )
    html = (
        f"<p>Your genotyping job for kit <b>{kit_code}</b> failed.</p>"
        f"<pre>{error}</pre>"
        f'<p><a href="{url}">Job details</a></p>'
    )
    _send(to, subject, html, text)
