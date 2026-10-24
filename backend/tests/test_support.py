import json

from sqlalchemy import select

from app import db as app_db
from app import settings_store
from app.models import SupportTicket

from .conftest import enable_email, sign_up

TICKET = {"category": "bug", "subject": "Save button does nothing", "message": "I click save and nothing happens at all.", "page": "/create"}


async def test_signed_out_request_and_admin_reply(client, outbox):
    await enable_email()
    async with app_db.sessionmaker()() as db:
        await settings_store.save(db, {"support_email": "help@example.com"})
    r = await client.post("/api/support", json={**TICKET, "name": "Sam", "email": "Sam@Example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["number"] == 1001 and r.json()["id"] is None   # signed-out people can't open it on the site
    assert {m["to"] for m in outbox} == {"help@example.com", "sam@example.com"}
    second = (await client.post("/api/support", json={**TICKET, "email": "sam@example.com"})).json()
    assert second["number"] == 1002
    assert (await client.post("/api/support", json={**TICKET, "email": "not-an-email"})).status_code == 400
    assert (await client.post("/api/support", json={**TICKET, "category": "nope", "email": "a@b.co"})).status_code == 400
    bot = await client.post("/api/support", json={**TICKET, "email": "bot@example.com", "website": "http://spam"})
    assert bot.json()["number"] == 0
    async with app_db.sessionmaker()() as db:
        assert len((await db.execute(select(SupportTicket))).scalars().all()) == 2   # the bot's wasn't stored

    await sign_up(client, outbox, "admin@example.com")
    inbox = (await client.get("/api/admin/support", params={"status": "open"})).json()
    assert inbox["counts"]["open"] == 2 and inbox["tickets"][0]["preview"].startswith("I click save")
    tid = inbox["tickets"][0]["id"]
    outbox.clear()
    r = await client.post(f"/api/admin/support/{tid}/reply", json={"message": "Fixed now <b>thanks</b>", "status": "closed"})
    assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["emailed"]
    assert outbox[-1]["to"] == "sam@example.com" and "Fixed now <b>thanks</b>" in outbox[-1]["text"]
    assert (await client.get("/api/admin/support", params={"q": "#1002"})).json()["total"] == 1
    log = (await client.get("/api/admin/audit", params={"q": "#100"})).json()
    assert {e["action"] for e in log["entries"]} >= {"support.ticket_created", "admin.support.reply"}


async def test_signed_in_conversation(client, outbox):
    await sign_up(client, outbox, "fan@example.com")
    r = (await client.post("/api/support", json=TICKET)).json()   # email comes from the account
    assert r["id"]
    mine = (await client.get("/api/support/tickets")).json()
    assert len(mine) == 1 and mine[0]["status"] == "open" and mine[0]["messages"][0]["from"] == "user"
    async with app_db.sessionmaker()() as db:
        t = await db.get(SupportTicket, r["id"])
        assert t.email == "fan@example.com" and t.context["page"] == "/create"
        t.messages = [*t.messages, {"from": "admin", "body": "Which browser?", "at": "2026-10-25T00:00:00", "author": "Jamie Admin"}]
        t.status = "waiting"
        await db.commit()
    mine = (await client.get("/api/support/tickets")).json()
    assert mine[0]["messages"][-1]["author"] == "Support"   # admin names stay private
    r = await client.post(f"/api/support/tickets/{mine[0]['id']}/reply", json={"message": "Firefox"})
    assert r.json()["status"] == "open"
    assert (await client.post(f"/api/support/tickets/{mine[0]['id']}/close")).json()["status"] == "closed"
    export = (await client.get("/api/me/export")).json()
    assert export["support_requests"][0]["number"] == 1001 and "Jamie" not in json.dumps(export)

    await client.post("/api/auth/logout")
    await sign_up(client, outbox, "other@example.com")
    assert (await client.get("/api/support/tickets")).json() == []
    assert (await client.post(f"/api/support/tickets/{r.json()['id']}/reply", json={"message": "hi"})).status_code == 404


async def test_support_can_be_turned_off(client):
    async with app_db.sessionmaker()() as db:
        await settings_store.save(db, {"support_enabled": False})
    assert (await client.post("/api/support", json={**TICKET, "email": "a@b.co"})).status_code == 503
