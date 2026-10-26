import json
import time

import httpx
import respx
from sqlalchemy import select

from app import db as app_db
from app import settings_store
from app.models import Plan, User
from app.services.stripe import _form, sign_for_tests, verify_webhook

from .conftest import connect_spotify, sign_up

WEBHOOK_SECRET = "whsec_test"


async def configure_stripe():
    async with app_db.sessionmaker()() as db:
        await settings_store.save(db, {"billing_enabled": True, "stripe_secret_key": "sk_test_abc", "stripe_webhook_secret": WEBHOOK_SECRET})


def mock_catalogue():
    products = respx.post("https://api.stripe.com/v1/products").mock(return_value=httpx.Response(200, json={"id": "prod_1"}))
    prices = respx.post("https://api.stripe.com/v1/prices").mock(side_effect=[
        httpx.Response(200, json={"id": "price_1"}), httpx.Response(200, json={"id": "price_2"})])
    respx.post("https://api.stripe.com/v1/products/prod_1").mock(return_value=httpx.Response(200, json={"id": "prod_1"}))
    archived = respx.post("https://api.stripe.com/v1/prices/price_1").mock(return_value=httpx.Response(200, json={"id": "price_1"}))
    return products, prices, archived


PRO = {"name": "Pro", "price_cents": 500, "currency": "nzd", "interval": "month", "monthly_token_limit": 5_000_000,
       "daily_generation_limit": 200, "perks": ["Edit your playlists", " "], "allow_edit_playlists": True}
FREE = {"name": "Free", "is_default": True, "daily_generation_limit": 3, "allow_edit_playlists": False, "allow_playlist_seeds": False}


def test_form_encoding():
    assert _form({"line_items": [{"price": "p", "quantity": 1}], "recurring": {"interval": "month"}, "x": None, "b": True}) == [
        ("line_items[0][price]", "p"), ("line_items[0][quantity]", "1"), ("recurring[interval]", "month"), ("b", "true")]


def test_webhook_signature():
    body = json.dumps({"type": "ping"}).encode()
    assert verify_webhook(body, sign_for_tests(body, "s"), "s")["type"] == "ping"
    for header in (sign_for_tests(body, "wrong"), sign_for_tests(body, "s", ts=int(time.time()) - 3600), "garbage"):
        try:
            verify_webhook(body, header, "s")
            raise AssertionError("accepted a bad signature")
        except Exception as e:
            assert type(e).__name__ == "StripeError"


@respx.mock
async def test_plan_crud_syncs_to_stripe(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    await configure_stripe()
    products, prices, archived = mock_catalogue()
    r = await client.post("/api/admin/plans", json=PRO)
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert r.json()["warning"] is None and plan["stripe_price_id"] == "price_1" and plan["perks"] == ["Edit your playlists"]
    sent = prices.calls[0].request.content.decode()
    assert "unit_amount=500" in sent and "recurring%5Binterval%5D=month" in sent and "currency=nzd" in sent
    r = await client.patch(f"/api/admin/plans/{plan['id']}", json={**PRO, "price_cents": 700})
    assert r.json()["plan"]["stripe_price_id"] == "price_2" and archived.called
    # renaming without a price change doesn't make a new price
    r = await client.patch(f"/api/admin/plans/{plan['id']}", json={**PRO, "price_cents": 700, "name": "Pro+"})
    assert r.json()["plan"]["stripe_price_id"] == "price_2" and prices.call_count == 2
    pub = (await client.get("/api/plans")).json()
    assert pub["billing_enabled"] and pub["plans"][0]["purchasable"]


async def test_paid_plan_without_stripe_key_warns(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    r = await client.post("/api/admin/plans", json=PRO)
    assert "Stripe secret key" in r.json()["warning"] and r.json()["plan"]["purchasable"] is False


async def test_default_plan_limits_features_and_overrides(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    free = (await client.post("/api/admin/plans", json=FREE)).json()["plan"]
    me = (await client.get("/api/me")).json()
    assert me["membership"]["plan"]["name"] == "Free" and me["usage"]["daily_limit"] == 3
    assert me["membership"]["features"] == {"edit_playlists": False, "playlist_seeds": False}
    assert (await client.post("/api/generations/import", json={"playlist_id": "x"})).status_code == 403
    # per-user override beats the plan; blank fields reset just those
    r = await client.patch(f"/api/admin/users/{me['id']}", json={"clear_limits": True, "daily_generation_limit": 9})
    assert r.status_code == 200
    me = (await client.get("/api/me")).json()
    assert me["usage"]["daily_limit"] == 9
    assert {"requests_today", "tokens_today", "tokens_this_month", "daily_token_limit", "monthly_token_limit"} <= me["usage"].keys()
    assert free["members"] == 0


@respx.mock
async def test_checkout_webhook_and_cancel(client, outbox):
    await sign_up(client, outbox, "payer@example.com")
    await connect_spotify("payer@example.com")
    me = (await client.get("/api/me")).json()
    await configure_stripe()
    async with app_db.sessionmaker()() as db:
        db.add(Plan(name="Free", is_default=True, daily_generation_limit=3))
        pro = Plan(name="Pro", price_cents=500, currency="nzd", stripe_price_id="price_1", daily_generation_limit=200)
        db.add(pro)
        await db.commit()
        pro_id = pro.id
    respx.post("https://api.stripe.com/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_1"}))
    session = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"}))
    r = await client.post("/api/billing/checkout", json={"plan_id": pro_id})
    assert r.status_code == 200, r.text and r.json()["url"].startswith("https://checkout.stripe.com")
    body = session.calls[0].request.content.decode()
    assert "customer=cus_1" in body and f"client_reference_id={me['id']}" in body and "mode=subscription" in body

    sub = {"id": "sub_1", "object": "subscription", "customer": "cus_1", "status": "active", "cancel_at_period_end": False,
           "items": {"data": [{"price": {"id": "price_1", "metadata": {"plan_id": pro_id}}, "current_period_end": int(time.time()) + 86400 * 30}]}}
    respx.get("https://api.stripe.com/v1/subscriptions/sub_1").mock(return_value=httpx.Response(200, json=sub))

    async def send(event):
        payload = json.dumps(event).encode()
        return await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": sign_for_tests(payload, WEBHOOK_SECRET)})

    assert (await client.post("/api/billing/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=bad"})).status_code == 400
    r = await send({"type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "subscription": "sub_1", "customer": "cus_1", "client_reference_id": me["id"]}}})
    assert r.status_code == 200, r.text
    m = (await client.get("/api/me")).json()
    assert m["membership"]["plan"]["name"] == "Pro" and m["membership"]["status"] == "active" and m["usage"]["daily_limit"] == 200
    # already subscribed: checkout refuses, portal works
    assert (await client.post("/api/billing/checkout", json={"plan_id": pro_id})).status_code == 409
    respx.post("https://api.stripe.com/v1/billing_portal/sessions").mock(return_value=httpx.Response(200, json={"url": "https://billing.stripe.com/p/1"}))
    assert (await client.post("/api/billing/portal")).json()["url"].startswith("https://billing.stripe.com")
    # cancelled -> back to the default plan
    r = await send({"type": "customer.subscription.deleted", "data": {"object": {**sub, "status": "canceled"}}})
    assert r.status_code == 200
    m = (await client.get("/api/me")).json()
    assert m["membership"]["plan"]["name"] == "Free" and m["usage"]["daily_limit"] == 3
    async with app_db.sessionmaker()() as db:
        u = await db.get(User, me["id"])
        assert u.plan_id is None and u.subscription_status == "canceled"


async def test_missing_asset_is_404_not_html(client):
    r = await client.get("/assets/index-OLDHASH.js")
    assert r.status_code == 404 and r.headers["cache-control"] == "no-store"


@respx.mock
async def test_ids_from_other_stripe_keys_are_replaced(client, outbox):
    """Switching test → live keys (or accounts): saved product, price and customer ids don't exist there."""
    await sign_up(client, outbox, "admin@example.com")
    await connect_spotify("admin@example.com")
    await configure_stripe()
    async with app_db.sessionmaker()() as db:
        db.add(Plan(name="Pro", price_cents=500, currency="nzd", interval="month", active=True,
                    stripe_product_id="prod_old", stripe_price_id="price_old"))
        me = (await db.execute(select(User))).scalars().first()
        me.stripe_customer_id = "cus_old"
        await db.commit()
    missing = lambda kind: httpx.Response(404, json={"error": {"code": "resource_missing", "message": f"No such {kind}"}})  # noqa: E731
    respx.post("https://api.stripe.com/v1/products/prod_old").mock(return_value=missing("product: 'prod_old'"))
    respx.post("https://api.stripe.com/v1/products").mock(return_value=httpx.Response(200, json={"id": "prod_new"}))
    prices = respx.post("https://api.stripe.com/v1/prices").mock(return_value=httpx.Response(200, json={"id": "price_new"}))
    r = (await client.post("/api/admin/plans/resync")).json()
    assert r == {"ok": True, "warnings": []}
    assert dict(_form_pairs(prices.calls[0].request))["product"] == "prod_new"
    plan = (await client.get("/api/admin/plans")).json()[0]
    assert plan["stripe_price_id"] == "price_new"

    respx.post("https://api.stripe.com/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_new"}))
    sessions = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(side_effect=[
        httpx.Response(400, json={"error": {"code": "resource_missing", "message": "No such customer: 'cus_old'"}}),
        httpx.Response(200, json={"url": "https://checkout.stripe.com/x"})])
    r = await client.post("/api/billing/checkout", json={"plan_id": plan["id"]})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout")
    assert dict(_form_pairs(sessions.calls[1].request))["customer"] == "cus_new"


def _form_pairs(request):
    from urllib.parse import parse_qsl
    return parse_qsl(request.content.decode())


async def test_checkout_needs_spotify(client, outbox):
    await sign_up(client, outbox, "payer@example.com")
    await configure_stripe()
    async with app_db.sessionmaker()() as db:
        pro = Plan(name="Pro", price_cents=500, currency="nzd", stripe_price_id="price_1")
        db.add(pro)
        await db.commit()
        pro_id = pro.id
    r = await client.post("/api/billing/checkout", json={"plan_id": pro_id})
    assert r.status_code == 400 and "Connect your Spotify" in r.json()["detail"]
