import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-user overrides; NULL means "use the site default"
    daily_generation_limit: Mapped[int | None] = mapped_column(Integer)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer)
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer)
    allowed_model_ids: Mapped[list[str] | None] = mapped_column(JSON)   # LLMModel ids; NULL = all enabled
    # Membership: NULL plan = the default (free) plan. plan_source: "stripe" (kept in sync by webhooks) or "admin"
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"), index=True)
    plan_source: Mapped[str | None] = mapped_column(String(10))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), index=True)
    subscription_status: Mapped[str | None] = mapped_column(String(24))   # Stripe status: active, past_due, canceled…
    subscription_period_end: Mapped[datetime | None] = mapped_column()
    subscription_cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column()

    identities: Mapped[list["Identity"]] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    spotify: Mapped["SpotifyConnection | None"] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True, uselist=False)


class Identity(Base):
    """A way to sign in to an account: spotify (subject = Spotify user id), google / apple (sub), email (address)."""

    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(320))
    email: Mapped[str | None] = mapped_column(String(320))   # the address the provider reported, shown in account settings
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User] = relationship(back_populates="identities")


class SpotifyConnection(Base):
    """The user's linked Spotify account and the Spotify app (Client ID) it was authorised through."""

    __tablename__ = "spotify_connections"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    spotify_user_id: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    client_id: Mapped[str] = mapped_column(String(64))
    uses_site_app: Mapped[bool] = mapped_column(Boolean, default=True)
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column()
    scopes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="spotify")


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class EmailToken(Base):
    """One-time link tokens for email verification and password reset (stored hashed)."""

    __tablename__ = "email_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    purpose: Mapped[str] = mapped_column(String(20))   # "verify" | "reset"
    user_id: Mapped[str | None] = mapped_column(String(32))   # set when a signed-in user asked to confirm their address
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
    used_at: Mapped[datetime | None] = mapped_column()


class Setting(Base):
    """Admin-editable site settings. Secret values are stored encrypted (see settings_store)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))   # anthropic | openai | gemini | openai_compatible
    base_url: Mapped[str | None] = mapped_column(String(1024))
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    models: Mapped[list["LLMModel"]] = relationship(back_populates="provider", cascade="all, delete-orphan", passive_deletes=True)


class LLMModel(Base):
    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(ForeignKey("llm_providers.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[str] = mapped_column(String(200))           # the provider's model name
    display_name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=16000)   # includes thinking on reasoning models
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    provider: Mapped[LLMProvider] = relationship(back_populates="models")


class UserLLMKey(Base):
    """A user's own API key for a provider kind; used instead of the site's key when they choose it."""

    __tablename__ = "user_llm_keys"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    base_url: Mapped[str | None] = mapped_column(String(1024))
    api_key_enc: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(200))           # which model to run with this key
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Generation(Base):
    """One playlist being designed: the request, the conversation, the current track list."""

    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    request: Mapped[dict] = mapped_column(JSON)              # guided fields or free-text prompt
    model_label: Mapped[str] = mapped_column(String(200), default="")
    messages: Mapped[list] = mapped_column(JSON, default=list)   # chat turns [{role, content}]
    tracks: Mapped[list] = mapped_column(JSON, default=list)     # [{title, artist, reason, spotify|null}]
    spotify_playlist_id: Mapped[str | None] = mapped_column(String(64))
    spotify_playlist_url: Mapped[str | None] = mapped_column(String(512))
    spotify_public: Mapped[bool] = mapped_column(Boolean, default=False)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)            # owner lets it appear, anonymously, on the community feed
    community_hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # an admin took it off the feed
    featured: Mapped[bool] = mapped_column(Boolean, default=False)          # unused (landing page now shows Spotify's catalogue)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class UsageLog(Base):
    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    generation_id: Mapped[str | None] = mapped_column(String(32))
    provider_kind: Mapped[str] = mapped_column(String(30))
    model_id: Mapped[str] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    own_key: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Plan(Base):
    """A membership level. Limits left NULL fall back to the site defaults; price 0 = free."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, default="")
    perks: Mapped[list[str]] = mapped_column(JSON, default=list)          # bullet points on the pricing page
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    interval: Mapped[str] = mapped_column(String(5), default="month")    # month | year
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)     # plan for everyone without a subscription
    active: Mapped[bool] = mapped_column(Boolean, default=True)          # offered on the pricing page
    highlight: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    daily_generation_limit: Mapped[int | None] = mapped_column(Integer)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer)
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer)
    max_playlist_size: Mapped[int | None] = mapped_column(Integer)
    allow_edit_playlists: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_playlist_seeds: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_model_ids: Mapped[list[str] | None] = mapped_column(JSON)
    default_model_id: Mapped[str | None] = mapped_column(String(32))     # LLMModel members start on; NULL = site default
    allow_model_choice: Mapped[bool | None] = mapped_column(Boolean)      # NULL = the site setting
    stripe_product_id: Mapped[str | None] = mapped_column(String(64))
    stripe_price_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Promotion(Base):
    """A free trial and/or a percentage off paid plans at checkout: automatic (no code) or for people who enter the code."""

    __tablename__ = "promotions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))                          # shown on the pricing page, e.g. "Launch special"
    code: Mapped[str | None] = mapped_column(String(40), unique=True)      # upper case; NULL = applies automatically
    plan_ids: Mapped[list[str] | None] = mapped_column(JSON)               # NULL = every paid plan
    trial_days: Mapped[int | None] = mapped_column(Integer)
    percent_off: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[str] = mapped_column(String(10), default="once")      # once | repeating | forever (Stripe coupon terms)
    duration_months: Mapped[int | None] = mapped_column(Integer)           # for "repeating"
    starts_at: Mapped[datetime | None] = mapped_column()
    ends_at: Mapped[datetime | None] = mapped_column()
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redemptions: Mapped[int] = mapped_column(Integer, default=0)         # completed checkouts
    reserved: Mapped[int] = mapped_column(Integer, default=0)            # checkouts started and still open
    first_subscription_only: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    stripe_coupon_id: Mapped[str | None] = mapped_column(String(64))       # made at first checkout; cleared when the terms change
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    """Who did what: admin changes, sign-ins, account and billing events. Kept after the actor or target is deleted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True)    # NULL = system, Stripe or an anonymous visitor
    actor_label: Mapped[str] = mapped_column(String(320), default="")
    action: Mapped[str] = mapped_column(String(60), index=True)            # e.g. "admin.user.update", "auth.login"
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(64), index=True)
    target_label: Mapped[str] = mapped_column(String(320), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")


class BillingEvent(Base):
    """Every Stripe webhook event received, by Stripe's event id (so retries are only applied once)."""

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(500), default="")
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    stripe_created_at: Mapped[datetime | None] = mapped_column()
    received_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class SupportTicket(Base):
    """A question or problem sent from the support page. `messages` is the conversation, oldest first."""

    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    number: Mapped[int] = mapped_column(Integer, unique=True)                # short reference shown to people, e.g. #1042
    user_id: Mapped[str | None] = mapped_column(String(32), index=True)    # NULL when sent while signed out; kept if the account goes
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(320))
    category: Mapped[str] = mapped_column(String(20))                      # bug | account | billing | spotify | feedback | other
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)   # open | waiting (on the user) | closed
    messages: Mapped[list] = mapped_column(JSON, default=list)             # [{from: "user"|"admin", body, at, author}]
    context: Mapped[dict] = mapped_column(JSON, default=dict)              # page, user agent, ip at submission
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
