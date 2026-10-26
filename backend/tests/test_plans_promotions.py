"""AI models per plan, lapsed subscriptions falling back to the default plan, and promotions at checkout."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import respx
from sqlalchemy import select

from app import crypto
from app import db as app_db
from app.models import LLMModel, LLMProvider, Plan, Promotion, SpotifyConnection, User
from app.services.stripe import sign_for_tests

from .conftest import sign_up
from .test_billing import WEBHOOK_SECRET, configure_stripe


async def setup_models_and_plans() -> dict:
    async with app_db.sessionmaker()() as db:
        prov = LLMProvider(name="Claude", kind="anthropic", api_key_enc=crypto.encrypt("sk-ant-x"), enabled=True)
        db.add(prov)
        await db.flush()
        cheap = LLMModel(provider=prov, model_id="claude-haiku-5-5", display_name="Claude Haiku 5.5", is_default=True)
        mid = LLMModel(provider=prov, model_id="claude-sonnet-5-5", display_name="Claude Sonnet 5.5", sort_order=1)
        top = LLMModel(provider=prov, model_id="claude-opus-5-5", display_name="Claude Opus 5.5", sort_order=2)
        db.add_all([cheap, mid, top])
        await db.flush()
        free = Plan(name="Free", is_default=True, allowed_model_ids=[cheap.id])
        plus = Plan(name="Plus", price_cents=500, currency="nzd", stripe_price_id="price_plus",
                    allowed_model_ids=[cheap.id, mid.id], default_model_id=mid.id)
        pro = Plan(name="Pro", price_cents=1500, currency="nzd", stripe_price_id="price_pro", default_model_id=top.id,
                   allow_model_choice=True, sort_order=1)
        db.add_all([free, plus, pro])
        for u in (await db.execute(select(User))).scalars():   # checkout needs Spotify connected
            db.add(SpotifyConnection(user_id=u.id, spotify_user_id=f"sp-{u.id[:8]}", client_id="a" * 32,
                                     access_token_enc="", refresh_token_enc="", expires_at=datetime.now(timezone.utc)))
        await db.commit()
        return {"cheap": cheap.id, "mid": mid.id, "top": top.id, "free": free.id, "plus": plus.id, "pro": pro.id}


async def put_on_plan(user_id: str, plan_id: str | None, period_end: datetime | None = None) -> None:
    async with app_db.sessionmaker()() as db:
        u = await db.get(User, user_id)
        u.plan_id, u.plan_source = plan_id, "stripe" if plan_id else None
        u.subscription_status = "active" if plan_id else None
        u.stripe_subscription_id = "sub_1" if plan_id else u.stripe_subscription_id
        u.subscription_period_end = period_end or datetime.now(timezone.utc) + timedelta(days=20)
        await db.commit()


async def my_models(client) -> list[tuple[str, bool]]:
    return [(m["label"], m["is_default"]) for m in (await client.get("/api/me")).json()["models"]]


async def test_models_follow_the_plan(client, outbox):
    await sign_up(client, outbox, "user@example.com")
    ids = await setup_models_and_plans()
    me = (await client.get("/api/me")).json()
    assert await my_models(client) == [("Claude Haiku 5.5", True)]                # free: the cheap model only
    await put_on_plan(me["id"], ids["plus"])
    assert await my_models(client) == [("Claude Sonnet 5.5", True)]               # plan default; site has choice off
    await put_on_plan(me["id"], ids["pro"])
    assert await my_models(client) == [("Claude Haiku 5.5", False), ("Claude Sonnet 5.5", False), ("Claude Opus 5.5", True)]

    plans = {p["name"]: p for p in (await client.get("/api/plans")).json()["plans"]}
    assert plans["Free"]["models"] == ["Claude Haiku 5.5"] and not plans["Free"]["model_choice"]
    assert plans["Plus"]["models"] == ["Claude Sonnet 5.5"]
    assert plans["Pro"]["models"] == ["Claude Haiku 5.5", "Claude Sonnet 5.5", "Claude Opus 5.5"] and plans["Pro"]["model_choice"]


async def test_lapsed_subscription_falls_back_to_default_plan(client, outbox):
    """If Stripe's 'subscription ended' webhook never arrives, the paid plan still stops a few days after the period."""
    await sign_up(client, outbox, "user@example.com")
    ids = await setup_models_and_plans()
    me = (await client.get("/api/me")).json()
    await put_on_plan(me["id"], ids["pro"], datetime.now(timezone.utc) - timedelta(days=1))
    assert (await client.get("/api/me")).json()["membership"]["plan"]["name"] == "Pro"     # within the grace period
    await put_on_plan(me["id"], ids["pro"], datetime.now(timezone.utc) - timedelta(days=4))
    assert (await client.get("/api/me")).json()["membership"]["plan"]["name"] == "Free"
    assert await my_models(client) == [("Claude Haiku 5.5", True)]


async def test_admin_plan_default_model_must_be_allowed(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    ids = await setup_models_and_plans()
    body = {"name": "Odd", "allowed_model_ids": [ids["cheap"]], "default_model_id": ids["top"]}
    r = await client.post("/api/admin/plans", json=body)
    assert r.status_code == 400 and "must be one of" in r.json()["detail"]
    r = await client.post("/api/admin/plans", json={**body, "default_model_id": ids["cheap"], "allow_model_choice": False})
    assert r.status_code == 200 and r.json()["plan"]["raw"]["default_model_id"] == ids["cheap"]


async def make_promo(client, **fields) -> dict:
    r = await client.post("/api/admin/promotions", json={"name": "Launch special", **fields})
    assert r.status_code == 200, r.text
    return r.json()


async def test_promotion_validation_and_descriptions(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    assert (await client.post("/api/admin/promotions", json={"name": "Nothing"})).status_code == 400
    assert (await client.post("/api/admin/promotions", json={"name": "x", "percent_off": 50, "duration": "repeating"})).status_code == 400
    assert (await make_promo(client, trial_days=30))["summary"] == "30 days free"
    assert (await make_promo(client, percent_off=50, duration="repeating", duration_months=3))["summary"] == "Half price for 3 months"
    assert (await make_promo(client, trial_days=14, percent_off=25, duration="forever"))["summary"] == \
        "14 days free, then 25% off for as long as you stay subscribed"
    r = await client.post("/api/admin/promotions", json={"name": "x", "code": "TRY", "trial_days": 14})
    assert r.status_code == 400 and "can't give free days" in r.json()["detail"]   # Stripe codes are discounts only
    p = await make_promo(client, code=" summer25 ", percent_off=25)
    assert p["code"] == "SUMMER25" and p["warning"] and not p["on_stripe"]   # no Stripe key yet
    r = await client.post("/api/admin/promotions", json={"name": "dupe", "code": "Summer25", "percent_off": 3})
    assert r.status_code == 400 and "already uses" in r.json()["detail"]


@respx.mock
async def test_automatic_trial_at_checkout_and_redemption(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    ids = await setup_models_and_plans()
    await configure_stripe()
    promo = await make_promo(client, trial_days=30, plan_ids=[ids["pro"]])
    plans = {p["name"]: p for p in (await client.get("/api/plans")).json()["plans"]}
    assert plans["Pro"]["promotion"]["summary"] == "30 days free" and plans["Plus"]["promotion"] is None

    respx.post("https://api.stripe.com/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_1"}))
    session = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(return_value=httpx.Response(200, json={"url": "https://checkout.stripe.com/x"}))
    assert (await client.post("/api/billing/checkout", json={"plan_id": ids["pro"]})).status_code == 200
    sent = parse_qs(session.calls[0].request.content.decode())
    assert sent["subscription_data[trial_period_days]"] == ["30"] and sent["metadata[promotion_id]"] == [promo["id"]]
    assert "discounts[0][coupon]" not in sent and sent["allow_promotion_codes"] == ["true"]   # a code can go on top of a trial

    me = (await client.get("/api/me")).json()
    sub = {"id": "sub_1", "customer": "cus_1", "status": "trialing", "items": {"data": [
        {"price": {"id": "price_pro"}, "current_period_end": int(datetime.now(timezone.utc).timestamp()) + 30 * 86400}]}}
    respx.get("https://api.stripe.com/v1/subscriptions/sub_1").mock(return_value=httpx.Response(200, json=sub))
    payload = json.dumps({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "subscription": "sub_1", "customer": "cus_1", "client_reference_id": me["id"],
        "metadata": {"promotion_id": promo["id"]}}}}).encode()
    for _ in range(2):   # Stripe retries count once
        await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": sign_for_tests(payload, WEBHOOK_SECRET)})
    async with app_db.sessionmaker()() as db:
        assert (await db.get(Promotion, promo["id"])).redemptions == 1
    m = (await client.get("/api/me")).json()["membership"]
    assert m["plan"]["name"] == "Pro" and m["status"] == "trialing"   # a trial counts as subscribed


def mock_codes():
    coupons = respx.post("https://api.stripe.com/v1/coupons").mock(side_effect=[
        httpx.Response(200, json={"id": f"co_{i}"}) for i in range(1, 6)])
    created = respx.post("https://api.stripe.com/v1/promotion_codes").mock(side_effect=[
        httpx.Response(200, json={"id": f"promo_{i}"}) for i in range(1, 6)])
    updated = respx.post(url__regex=r"https://api\.stripe\.com/v1/promotion_codes/promo_\d").mock(return_value=httpx.Response(200, json={}))
    return coupons, created, updated


def form(call) -> dict:
    return {k: v[0] for k, v in parse_qs(call.request.content.decode()).items()}


@respx.mock
async def test_code_promotion_is_a_stripe_promotion_code(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    ids = await setup_models_and_plans()
    await configure_stripe()
    async with app_db.sessionmaker()() as db:
        (await db.get(Plan, ids["plus"])).stripe_product_id = "prod_plus"
        await db.commit()
    coupons, created, updated = mock_codes()
    ends = datetime.now(timezone.utc) + timedelta(days=10)
    p = await make_promo(client, name="Half price", code="half", percent_off=50, duration="repeating", duration_months=3,
                         plan_ids=[ids["plus"]], max_redemptions=20, ends_at=ends.isoformat())
    assert p["on_stripe"] and p["warning"] is None
    c = form(coupons.calls[0])
    assert (c["percent_off"], c["duration"], c["duration_in_months"], c["applies_to[products][0]"]) == ("50", "repeating", "3", "prod_plus")
    code = form(created.calls[0])
    assert (code["coupon"], code["code"], code["active"], code["max_redemptions"]) == ("co_1", "HALF", "true", "20")
    assert int(code["expires_at"]) == int(ends.timestamp()) and code["restrictions[first_time_transaction]"] == "true"
    assert created.calls[0].request.headers["stripe-version"] == "2024-06-20"
    assert (await client.get("/api/plans")).json()["plans"][1]["promotion"] is None   # codes aren't shown on the cards

    # checkout lets the customer type a code at Stripe
    respx.post("https://api.stripe.com/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_1"}))
    session = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(return_value=httpx.Response(200, json={"url": "https://checkout.stripe.com/x"}))
    assert (await client.post("/api/billing/checkout", json={"plan_id": ids["plus"]})).status_code == 200
    assert form(session.calls[0])["allow_promotion_codes"] == "true"

    # pausing only switches the code off; changing the discount replaces code and coupon
    body = {"name": "Half price", "code": "HALF", "percent_off": 50, "duration": "repeating", "duration_months": 3,
            "plan_ids": [ids["plus"]], "max_redemptions": 20, "ends_at": ends.isoformat()}
    await client.patch(f"/api/admin/promotions/{p['id']}", json={**body, "active": False})
    assert created.call_count == 1 and form(updated.calls[-1]) == {"active": "false"}
    r = await client.patch(f"/api/admin/promotions/{p['id']}", json={**body, "percent_off": 40})
    assert created.call_count == 2 and coupons.call_count == 2 and r.json()["on_stripe"]
    assert str(updated.calls[-1].request.url).endswith("/promo_1") and form(updated.calls[-1]) == {"active": "false"}

    # deleting switches it off in Stripe
    assert (await client.delete(f"/api/admin/promotions/{p['id']}")).status_code == 200
    assert str(updated.calls[-1].request.url).endswith("/promo_2")


@respx.mock
async def test_code_redemption_counted_from_checkout(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    await setup_models_and_plans()
    await configure_stripe()
    mock_codes()
    p = await make_promo(client, code="SAVE", percent_off=20)
    me = (await client.get("/api/me")).json()
    sub = {"id": "sub_1", "customer": "cus_1", "status": "active", "items": {"data": [{"price": {"id": "price_plus"}}]}}
    respx.get("https://api.stripe.com/v1/subscriptions/sub_1").mock(return_value=httpx.Response(200, json=sub))
    await send_event(client, {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "subscription": "sub_1", "customer": "cus_1", "client_reference_id": me["id"],
        "discounts": [{"coupon": None, "promotion_code": "promo_1"}]}}})
    admin = (await client.get("/api/admin/promotions")).json()[0]
    assert admin["id"] == p["id"] and admin["redemptions"] == 1


@respx.mock
async def test_scheduled_code_switches_on_when_it_starts(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    await setup_models_and_plans()
    await configure_stripe()
    _, created, updated = mock_codes()
    p = await make_promo(client, code="SOON", percent_off=10, starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    assert form(created.calls[0])["active"] == "false" and p["status"] == "Scheduled"
    await client.get("/api/plans")
    assert updated.call_count == 0                       # not yet
    async with app_db.sessionmaker()() as db:
        (await db.get(Promotion, p["id"])).starts_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    await client.get("/api/plans")                       # someone opens the pricing page
    assert form(updated.calls[0]) == {"active": "true"}
    await client.get("/api/plans")
    assert updated.call_count == 1                       # told Stripe once


@respx.mock
async def test_automatic_promotion_rules(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    ids = await setup_models_and_plans()
    await configure_stripe()
    me = (await client.get("/api/me")).json()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await make_promo(client, name="Over", percent_off=90, ends_at=past)
    await make_promo(client, name="Pro only", trial_days=7, plan_ids=[ids["pro"]], first_subscription_only=False)
    await make_promo(client, name="New only", percent_off=50, plan_ids=[ids["plus"]])
    shown = lambda plans: {p["name"]: (p["promotion"] or {}).get("name") for p in plans["plans"] if p["price_cents"]}  # noqa: E731
    assert shown((await client.get("/api/plans")).json()) == {"Plus": "New only", "Pro": "Pro only"}
    async with app_db.sessionmaker()() as db:
        u = await db.get(User, me["id"])
        u.stripe_subscription_id, u.subscription_status = "sub_old", "canceled"   # subscribed before
        await db.commit()
    assert shown((await client.get("/api/plans")).json()) == {"Plus": None, "Pro": "Pro only"}



async def send_event(client, event: dict):
    payload = json.dumps(event).encode()
    return await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": sign_for_tests(payload, WEBHOOK_SECRET)})


@respx.mock
async def test_last_use_is_held_during_checkout_and_released_if_abandoned(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    ids = await setup_models_and_plans()
    await configure_stripe()
    promo = await make_promo(client, name="One only", trial_days=7, max_redemptions=1)
    respx.post("https://api.stripe.com/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_1"}))
    session = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(return_value=httpx.Response(200, json={"url": "https://checkout.stripe.com/x"}))
    assert (await client.post("/api/billing/checkout", json={"plan_id": ids["pro"]})).status_code == 200
    sent = parse_qs(session.calls[0].request.content.decode())
    assert sent["subscription_data[trial_period_days]"] == ["7"]
    window = int(sent["expires_at"][0]) - datetime.now(timezone.utc).timestamp()
    assert 30 * 60 < window <= 3600

    # someone else checking out meanwhile doesn't get it: the use is held
    plans = {p["name"]: p for p in (await client.get("/api/plans")).json()["plans"]}
    assert plans["Pro"]["promotion"] is None
    assert (await client.post("/api/billing/checkout", json={"plan_id": ids["pro"]})).status_code == 200
    assert "subscription_data[trial_period_days]" not in parse_qs(session.calls[1].request.content.decode())
    admin = (await client.get("/api/admin/promotions")).json()[0]
    assert (admin["redemptions"], admin["reserved"], admin["status"]) == (0, 1, "Used up")

    # the first checkout is abandoned: the use comes back
    r = await send_event(client, {"id": "evt_x", "type": "checkout.session.expired", "data": {"object": {
        "customer": "cus_1", "metadata": {"promotion_id": promo["id"]}}}})
    assert r.status_code == 200
    admin = (await client.get("/api/admin/promotions")).json()[0]
    assert (admin["redemptions"], admin["reserved"], admin["status"]) == (0, 0, "Running")



@respx.mock
async def test_limited_discount_held_and_stripe_failure_releases_hold(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    ids = await setup_models_and_plans()
    await configure_stripe()
    await make_promo(client, name="Half", percent_off=50, max_redemptions=1)
    respx.post("https://api.stripe.com/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_1"}))
    respx.post("https://api.stripe.com/v1/coupons").mock(return_value=httpx.Response(200, json={"id": "co_1"}))
    session = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(side_effect=[
        httpx.Response(500, json={"error": {"message": "Stripe is down"}}),
        httpx.Response(200, json={"url": "https://checkout.stripe.com/x"}), httpx.Response(200, json={"url": "https://checkout.stripe.com/y"})])
    checkout = lambda: client.post("/api/billing/checkout", json={"plan_id": ids["plus"]})  # noqa: E731
    assert (await checkout()).status_code == 424          # failed: hold given back
    assert (await checkout()).status_code == 200          # so this one gets it
    sent = form(session.calls[1])
    assert sent["discounts[0][coupon]"] == "co_1" and "allow_promotion_codes" not in sent   # Stripe: discount or code box
    assert (await checkout()).status_code == 200          # the next person pays full price and may type a code
    sent = form(session.calls[2])
    assert "discounts[0][coupon]" not in sent and sent["allow_promotion_codes"] == "true"



async def test_checkout_closes_when_promotion_ends():
    from app import promotions
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    p = Promotion(name="x", trial_days=7, ends_at=now + timedelta(minutes=45))
    assert promotions.checkout_expiry(p, now) == int((now + timedelta(minutes=45)).timestamp())
    p.ends_at = now + timedelta(days=3)
    assert promotions.checkout_expiry(p, now) == int((now + timedelta(hours=1)).timestamp())
    p.ends_at = now + timedelta(minutes=5)   # Stripe's minimum is 30 minutes
    assert promotions.checkout_expiry(p, now) == int((now + timedelta(minutes=31)).timestamp())
