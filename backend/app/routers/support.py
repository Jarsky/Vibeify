"""Support requests: anyone can send one; signed-in people can follow theirs; admins answer from the admin panel.

Replies are kept on the request, so the conversation works without email. With SMTP set up, new requests are
emailed to `support_email` and people get an email when an admin replies.
"""
import html
import logging
import re

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, mailer, ratelimit, security, settings_store
from ..config import get_config
from ..db import get_db, utcnow
from ..models import SupportTicket, User, new_id

log = logging.getLogger("vibeify.support")
router = APIRouter(prefix="/api", tags=["support"], dependencies=[Depends(security.csrf_guard)])

CATEGORIES = {"bug": "Something isn't working", "account": "Account & sign-in", "billing": "Billing & plans",
              "spotify": "Spotify connection", "feedback": "Feedback & ideas", "other": "Something else"}
STATUSES = ("open", "waiting", "closed")
FIRST_NUMBER = 1001


class TicketIn(BaseModel):
    name: str = Field("", max_length=120)
    email: str = Field("", max_length=320)
    category: str
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=10, max_length=5000)
    page: str = Field("", max_length=300)
    website: str = ""   # honeypot: people never see this field, bots fill it in


class ReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


def _message(sender: str, body: str, author: str) -> dict:
    return {"from": sender, "body": body.strip(), "at": utcnow().isoformat(), "author": author}


def _view(t: SupportTicket, *, admin: bool = False) -> dict:
    out = {"id": t.id, "number": t.number, "category": t.category, "subject": t.subject, "status": t.status,
           "created_at": t.created_at, "updated_at": t.updated_at,
           # people see "Support" on admin replies, not which admin wrote them
           "messages": t.messages if admin else [{**m, "author": "Support" if m["from"] == "admin" else m["author"]} for m in t.messages]}
    if admin:
        out.update(name=t.name, email=t.email, user_id=t.user_id, context=t.context)
    return out


def _email_body(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


async def _notify(settings: dict, to: str, subject: str, heading: str, body: str, button: str, url: str) -> None:
    """Best effort: a failed email never loses the request or the reply."""
    if not (to and settings_store.email_ready(settings)):
        return
    _, page = mailer.link_email(settings, heading=heading, body=_email_body(body), button=button, url=url)
    text = f"{heading}\n\n{body}\n\n{button}: {url}\n\n— {settings['site_name']}"
    try:
        await mailer.send(settings, to, subject, text, page)
    except Exception:   # noqa: BLE001
        log.exception("support email to %s failed", to)


async def _own_ticket(db: AsyncSession, user: User, ticket_id: str) -> SupportTicket:
    t = await db.get(SupportTicket, ticket_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "Request not found.")
    return t


# ── people ───────────────────────────────────────────────────────────────────
@router.post("/support")
async def create_ticket(body: TicketIn, request: Request, user: User | None = Depends(security.optional_user),
                        db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    if not settings["support_enabled"]:
        raise HTTPException(503, "The support form is turned off on this site.")
    if body.category not in CATEGORIES:
        raise HTTPException(400, "Pick what your request is about.")
    raw_email = (body.email or (user.email if user else "") or "").strip()
    try:
        email = validate_email(raw_email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as e:
        raise HTTPException(400, "Enter an email address so we can reply.") from e
    ip = security.client_ip(request)
    ratelimit.limit(f"support:{ip}", 5, 3600)
    ratelimit.limit(f"support:{email}", 5, 3600)
    if body.website:   # a bot: pretend it worked
        return {"ok": True, "number": 0, "id": None}
    name = body.name.strip() or (user.display_name if user else "")
    subject = re.sub(r"\s+", " ", body.subject).strip()
    for attempt in range(3):   # numbers are sequential; retry if two requests land at once
        number = ((await db.execute(select(func.max(SupportTicket.number)))).scalar() or FIRST_NUMBER - 1) + 1
        t = SupportTicket(id=new_id(), number=number, user_id=user.id if user else None, name=name[:120], email=email, category=body.category,
                          subject=subject[:200], messages=[_message("user", body.message, name or email)],
                          context={"page": body.page[:300], "ip": ip, "user_agent": (request.headers.get("user-agent") or "")[:300],
                                   "signed_in": user is not None})
        db.add(t)
        audit.record(db, "support.ticket_created", request=request, actor=user, actor_label=None if user else email,
                     target_type="ticket", target_id=t.id, target_label=f"#{number} {subject}"[:320], category=body.category)
        try:
            await db.commit()
            break
        except IntegrityError:
            await db.rollback()
            if attempt == 2:
                raise
    base = get_config().public_url
    await _notify(settings, settings["support_email"], f"[{settings['site_name']} #{t.number}] {subject}",
                  f"New request #{t.number}: {CATEGORIES[t.category]}", f"From {name or email} <{email}>\n\n{body.message}",
                  "Open in admin", f"{base}/admin/support/{t.id}")
    await _notify(settings, email, f"We got your request #{t.number}", f"Thanks, we got your request #{t.number}",
                  f"We'll reply as soon as we can.\n\n“{subject}”", "See your request" if user else "Visit the site",
                  f"{base}/support?ticket={t.id}" if user else base)
    return {"ok": True, "number": t.number, "id": t.id if user else None}


@router.get("/support/tickets")
async def my_tickets(user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SupportTicket).where(SupportTicket.user_id == user.id)
                             .order_by(SupportTicket.updated_at.desc()).limit(50))).scalars().all()
    return [_view(t) for t in rows]


@router.post("/support/tickets/{ticket_id}/reply")
async def my_reply(ticket_id: str, body: ReplyIn, request: Request, user: User = Depends(security.current_user),
                   db: AsyncSession = Depends(get_db)):
    t = await _own_ticket(db, user, ticket_id)
    ratelimit.limit(f"support-reply:{user.id}", 20, 3600)
    t.messages = [*t.messages, _message("user", body.message, user.display_name or user.email or "You")]
    t.status = "open"
    await db.commit()
    settings = await settings_store.load(db)
    await _notify(settings, settings["support_email"], f"[{settings['site_name']} #{t.number}] {t.subject}",
                  f"New reply on #{t.number}", body.message, "Open in admin", f"{get_config().public_url}/admin/support/{t.id}")
    return _view(t)


@router.post("/support/tickets/{ticket_id}/close")
async def my_close(ticket_id: str, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    t = await _own_ticket(db, user, ticket_id)
    t.status = "closed"
    await db.commit()
    return _view(t)


# ── admin inbox ─────────────────────────────────────────────────────────────
admin_router = APIRouter(prefix="/api/admin/support", tags=["admin"],
                         dependencies=[Depends(security.csrf_guard), Depends(security.admin_user)])


@admin_router.get("")
async def admin_list(status: str = "", q: str = "", page: int = 1, db: AsyncSession = Depends(get_db)):
    stmt = select(SupportTicket).order_by(SupportTicket.updated_at.desc())
    if status:
        stmt = stmt.where(SupportTicket.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(SupportTicket.subject).like(like), func.lower(SupportTicket.email).like(like),
                              func.lower(SupportTicket.name).like(like), SupportTicket.number == (int(q.lstrip("#")) if q.lstrip("#").isdigit() else -1)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((max(page, 1) - 1) * 50).limit(50))).scalars().all()
    counts = dict((await db.execute(select(SupportTicket.status, func.count(SupportTicket.id)).group_by(SupportTicket.status))).all())
    return {"total": total, "page": page, "counts": {s: counts.get(s, 0) for s in STATUSES},
            "tickets": [{**_view(t, admin=True), "messages": None, "message_count": len(t.messages),
                         "last_from": t.messages[-1]["from"] if t.messages else None,
                         "preview": (t.messages[-1]["body"] if t.messages else "")[:160]} for t in rows]}


@admin_router.get("/{ticket_id}")
async def admin_get(ticket_id: str, db: AsyncSession = Depends(get_db)):
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(404, "Request not found.")
    out = _view(t, admin=True)
    u = await db.get(User, t.user_id) if t.user_id else None
    out["user"] = None if not u else {"id": u.id, "display_name": u.display_name, "email": u.email, "is_disabled": u.is_disabled}
    out["email_ready"] = settings_store.email_ready(await settings_store.load(db))
    return out


class AdminReplyIn(ReplyIn):
    status: str = "waiting"   # after replying: waiting (on them) or closed


@admin_router.post("/{ticket_id}/reply")
async def admin_reply(ticket_id: str, body: AdminReplyIn, request: Request, me: User = Depends(security.admin_user),
                      db: AsyncSession = Depends(get_db)):
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(404, "Request not found.")
    if body.status not in STATUSES:
        raise HTTPException(400, "Unknown status.")
    t.messages = [*t.messages, _message("admin", body.message, me.display_name or me.email or "Admin")]
    t.status = body.status
    audit.record(db, "admin.support.reply", request=request, actor=me, target_type="ticket", target_id=t.id,
                 target_label=f"#{t.number} {t.subject}"[:320], status=body.status)
    await db.commit()
    settings = await settings_store.load(db)
    base = get_config().public_url
    await _notify(settings, t.email, f"Re: {t.subject} [#{t.number}]", f"New reply to your request #{t.number}", body.message,
                  "Reply on the site" if t.user_id else "Visit the site", f"{base}/support?ticket={t.id}" if t.user_id else base)
    return {**_view(t, admin=True), "emailed": bool(settings_store.email_ready(settings))}


class StatusIn(BaseModel):
    status: str


@admin_router.patch("/{ticket_id}")
async def admin_status(ticket_id: str, body: StatusIn, request: Request, me: User = Depends(security.admin_user),
                       db: AsyncSession = Depends(get_db)):
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(404, "Request not found.")
    if body.status not in STATUSES:
        raise HTTPException(400, "Unknown status.")
    if t.status != body.status:
        audit.record(db, "admin.support.status", request=request, actor=me, target_type="ticket", target_id=t.id,
                     target_label=f"#{t.number} {t.subject}"[:320], changes={"status": [t.status, body.status]})
        t.status = body.status
    await db.commit()
    return _view(t, admin=True)
