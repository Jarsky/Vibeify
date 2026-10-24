"""Audit trail: record who did what. Entries are added to the caller's DB session and saved with its commit."""
from datetime import timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from .db import utcnow
from .models import AuditLog, User
from .security import client_ip


def label(user: User | None) -> str:
    if user is None:
        return ""
    return user.email or user.display_name or user.id


def record(db: AsyncSession, action: str, *, request: Request | None = None, actor: User | None = None,
           actor_label: str | None = None, target: User | None = None, target_type: str | None = None,
           target_id: str | None = None, target_label: str = "", **details: Any) -> None:
    """Queue an audit entry. `target` is a shortcut for a user target; details must be JSON-safe."""
    if target is not None:
        target_type, target_id, target_label = "user", target.id, label(target)
    db.add(AuditLog(
        actor_id=actor.id if actor else None, actor_label=actor_label if actor_label is not None else label(actor),
        action=action, target_type=target_type, target_id=target_id, target_label=target_label[:320],
        details={k: v for k, v in details.items() if v is not None}, ip=client_ip(request) if request else "",
    ))


def diff(obj: Any, fields: list[str], before: dict[str, Any]) -> dict[str, list]:
    """{field: [old, new]} for the fields that changed since `before` was taken."""
    return {f: [before[f], getattr(obj, f)] for f in fields if before[f] != getattr(obj, f)}


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


async def prune(db: AsyncSession, days: int) -> None:
    if days > 0:
        await db.execute(delete(AuditLog).where(AuditLog.created_at < utcnow() - timedelta(days=days)))
        await db.commit()
