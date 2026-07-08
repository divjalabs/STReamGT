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


def send_job_needs_confirmation(to: str, kit_code: str, public_id: str, observed: int, expected: int) -> None:
    url = _job_url(public_id)
    subject = f"[{settings.app_name}] Job {kit_code} paused: low read count"
    text = (
        f"Your genotyping job for kit {kit_code} was paused before running.\n"
        f"The FASTQ has {observed:,} reads, below the expected {expected:,}.\n\n"
        f"Confirm whether to run it anyway: {url}\n"
    )
    html = (
        f"<p>Your genotyping job for kit <b>{kit_code}</b> was paused before running.</p>"
        f"<p>The FASTQ has <b>{observed:,}</b> reads, below the expected <b>{expected:,}</b>.</p>"
        f'<p><a href="{url}">Confirm whether to run it anyway</a></p>'
    )
    _send(to, subject, html, text)


def send_new_user_registered(admin_emails: list[str], new_email: str, organisation: str | None) -> None:
    """Notify admins that a new client account was created."""
    if not admin_emails:
        return
    org = f" ({organisation})" if organisation else ""
    subject = f"[{settings.app_name}] New user registered: {new_email}"
    text = f"A new user registered: {new_email}{org}.\nGrant kit access at {settings.frontend_base_url}/admin/users\n"
    html = (
        f"<p>A new user registered: <b>{new_email}</b>{org}.</p>"
        f'<p><a href="{settings.frontend_base_url}/admin/users">Manage users &amp; grant kit access</a></p>'
    )
    for addr in admin_emails:
        _send(addr, subject, html, text)


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
