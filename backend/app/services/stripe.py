"""Stripe over its REST API: products/prices for plans, Checkout, the customer portal, and webhook verification."""
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

API = "https://api.stripe.com/v1"


class StripeError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _form(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's bracket encoding: {"line_items": [{"price": "p"}]} -> line_items[0][price]=p."""
    out: list[tuple[str, str]] = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, dict):
            out += _form(value, name)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                out += _form(item, f"{name}[{i}]") if isinstance(item, dict) else [(f"{name}[{i}]", str(item))]
        elif isinstance(value, bool):
            out.append((name, "true" if value else "false"))
        else:
            out.append((name, str(value)))
    return out


class Stripe:
    def __init__(self, secret_key: str, http: httpx.AsyncClient | None = None):
        if not secret_key:
            raise StripeError("Stripe isn't set up: add the secret key in the admin panel.")
        self.key = secret_key
        self.http = http

    async def call(self, method: str, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as http:
            client = self.http or http
            r = await client.request(method, f"{API}{path}", auth=(self.key, ""), params=params,
                                     content=urlencode(_form(data)) if data else None,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"} if data else None)
        body = r.json() if r.content else {}
        if r.status_code >= 400:
            raise StripeError((body.get("error") or {}).get("message") or f"Stripe error {r.status_code}", r.status_code)
        return body

    # -- catalogue ---------------------------------------------------------------
    async def account(self) -> dict:
        return await self.call("GET", "/account")

    async def create_product(self, name: str, description: str, plan_id: str) -> dict:
        return await self.call("POST", "/products", {"name": name, "description": description or None, "metadata": {"plan_id": plan_id}})

    async def update_product(self, product_id: str, name: str, description: str) -> dict:
        return await self.call("POST", f"/products/{product_id}", {"name": name, "description": description or ""})

    async def create_price(self, product_id: str, cents: int, currency: str, interval: str, plan_id: str) -> dict:
        return await self.call("POST", "/prices", {"product": product_id, "unit_amount": cents, "currency": currency,
                                                   "recurring": {"interval": interval}, "metadata": {"plan_id": plan_id}})

    async def archive_price(self, price_id: str) -> None:
        await self.call("POST", f"/prices/{price_id}", {"active": False})

    # -- customers & subscriptions -----------------------------------------------
    async def create_customer(self, email: str | None, name: str, user_id: str) -> dict:
        return await self.call("POST", "/customers", {"email": email, "name": name or None, "metadata": {"user_id": user_id}})

    async def checkout(self, customer: str, price: str, user_id: str, success_url: str, cancel_url: str) -> dict:
        return await self.call("POST", "/checkout/sessions", {
            "mode": "subscription", "customer": customer, "client_reference_id": user_id,
            "line_items": [{"price": price, "quantity": 1}], "success_url": success_url, "cancel_url": cancel_url,
            "allow_promotion_codes": True, "subscription_data": {"metadata": {"user_id": user_id}},
        })

    async def portal(self, customer: str, return_url: str) -> dict:
        return await self.call("POST", "/billing_portal/sessions", {"customer": customer, "return_url": return_url})

    async def subscription(self, subscription_id: str) -> dict:
        return await self.call("GET", f"/subscriptions/{subscription_id}")

    async def cancel_subscription(self, subscription_id: str) -> dict:
        """Cancel now (not at period end), e.g. when the account is deleted."""
        return await self.call("DELETE", f"/subscriptions/{subscription_id}")


def subscription_fields(sub: dict) -> dict:
    """The parts of a Stripe subscription the app stores. current_period_end moved onto items in newer API versions."""
    item = ((sub.get("items") or {}).get("data") or [{}])[0] or {}
    end = sub.get("current_period_end") or item.get("current_period_end")
    return {
        "subscription_id": sub.get("id"), "status": sub.get("status"), "customer": sub.get("customer"),
        "price_id": (item.get("price") or {}).get("id"),
        "period_end": datetime.fromtimestamp(end, timezone.utc) if end else None,
        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
    }


def verify_webhook(payload: bytes, header: str, secret: str, tolerance: int = 300) -> dict:
    """Check the Stripe-Signature header (HMAC-SHA256 over "timestamp.payload") and return the event."""
    if not secret:
        raise StripeError("Webhook secret not set.", 400)
    parts: dict[str, list[str]] = {}
    for piece in (header or "").split(","):
        k, _, v = piece.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        ts = int(parts["t"][0])
    except (KeyError, ValueError) as e:
        raise StripeError("Bad signature header.", 400) from e
    if abs(time.time() - ts) > tolerance:
        raise StripeError("Webhook timestamp too old.", 400)
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise StripeError("Webhook signature doesn't match.", 400)
    return json.loads(payload)


def sign_for_tests(payload: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    return f"t={ts},v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
