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


def send_reanalysis_requested(
    admin_emails: list[str], kit_code: str, public_id: str, requester_email: str, reason: str
) -> None:
    """Notify admins that a user asked to re-enable an analysed kit for another run."""
    if not admin_emails:
        return
    url = _job_url(public_id)
    kits_url = f"{settings.frontend_base_url.rstrip('/')}/admin/kits"
    subject = f"[{settings.app_name}] Reanalysis requested for kit {kit_code}"
    text = (
        f"{requester_email} requested reanalysis of kit {kit_code}.\n\n"
        f"Reason:\n{reason}\n\n"
        f"Job: {url}\n"
        f"To allow another run, set the kit status to 'reanalyse' at {kits_url}\n"
    )
    html = (
        f"<p><b>{requester_email}</b> requested reanalysis of kit <b>{kit_code}</b>.</p>"
        f"<p><b>Reason:</b></p><pre>{reason}</pre>"
        f'<p><a href="{url}">View the job</a> · '
        f'<a href="{kits_url}">Manage kits (set to reanalyse)</a></p>'
    )
    for addr in admin_emails:
        _send(addr, subject, html, text)


def send_error_reported(
    admin_emails: list[str], kit_code: str, public_id: str, requester_email: str,
    error: str, note: str | None = None,
) -> None:
    """Notify admins that a user reported a failed job's error."""
    if not admin_emails:
        return
    url = _job_url(public_id)
    subject = f"[{settings.app_name}] Error reported for kit {kit_code}"
    note_text = f"\nNote from {requester_email}:\n{note}\n" if note else ""
    note_html = f"<p><b>Note from {requester_email}:</b></p><pre>{note}</pre>" if note else ""
    text = (
        f"{requester_email} reported a failed job for kit {kit_code}.\n\n"
        f"Error:\n{error}\n{note_text}\nJob: {url}\n"
    )
    html = (
        f"<p><b>{requester_email}</b> reported a failed job for kit <b>{kit_code}</b>.</p>"
        f"<p><b>Error:</b></p><pre>{error}</pre>{note_html}"
        f'<p><a href="{url}">View the job</a></p>'
    )
    for addr in admin_emails:
        _send(addr, subject, html, text)


def send_password_reset(to: str, reset_url: str) -> None:
    subject = f"[{settings.app_name}] Password reset"
    text = (
        "We received a request to reset your password.\n\n"
        f"Reset it here (the link expires in 1 hour): {reset_url}\n\n"
        "If you didn't request this, you can ignore this email.\n"
    )
    html = (
        "<p>We received a request to reset your password.</p>"
        f'<p><a href="{reset_url}">Reset your password</a> (the link expires in 1 hour).</p>'
        "<p>If you didn't request this, you can safely ignore this email.</p>"
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
