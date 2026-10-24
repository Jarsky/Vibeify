"""Transactional email (verification and password-reset links) over the admin-configured SMTP server."""
from email.message import EmailMessage

import aiosmtplib

from .config import get_config


async def send(settings: dict, to: str, subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings["smtp_from"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    security = settings.get("smtp_security", "starttls")
    await aiosmtplib.send(
        msg,
        hostname=settings["smtp_host"],
        port=int(settings.get("smtp_port") or 587),
        username=settings.get("smtp_username") or None,
        password=settings.get("smtp_password") or None,
        use_tls=security == "ssl",
        start_tls=security == "starttls",
        timeout=20,
    )


def link_email(settings: dict, *, heading: str, body: str, button: str, url: str) -> tuple[str, str]:
    site = settings["site_name"]
    text = f"{heading}\n\n{body}\n\n{url}\n\nIf you didn't ask for this, you can ignore this email.\n— {site}"
    html = f"""<!doctype html><html><body style="margin:0;background:#0b0b10;font-family:Inter,Segoe UI,Arial,sans-serif;color:#e7e7ee">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 16px">
<table width="480" cellpadding="0" cellspacing="0" style="background:#15151d;border-radius:16px;padding:32px">
<tr><td style="font-size:20px;font-weight:700;color:#fff;padding-bottom:12px">{heading}</td></tr>
<tr><td style="font-size:15px;line-height:1.6;color:#b9b9c6;padding-bottom:24px">{body}</td></tr>
<tr><td><a href="{url}" style="display:inline-block;background:#1ed760;color:#06140a;font-weight:700;text-decoration:none;padding:12px 22px;border-radius:999px">{button}</a></td></tr>
<tr><td style="font-size:12px;color:#7a7a88;padding-top:24px">If the button doesn't work, paste this link into your browser:<br>{url}<br><br>If you didn't ask for this, ignore this email.</td></tr>
</table><div style="font-size:12px;color:#5b5b68;padding-top:16px">{site} · {get_config().public_url}</div></td></tr></table></body></html>"""
    return text, html
