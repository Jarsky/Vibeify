# Vibeify

**Describe the vibe. Get the playlist.** Vibeify is a web app that builds Spotify playlists with AI.
Describe what you want, or build it step by step (genres, artists, mood, era). Vibeify asks an AI model for songs,
finds each one on Spotify, and lets you refine the list in a chat ("more upbeat", "no ballads") before saving it to your library.

Vibeify is not affiliated with Spotify.

## Features

- **Multi-user.** Accounts with Spotify, Google, or email and password. Users manage their own Spotify connection and, if the admin allows it, their own AI keys.
- **Bring your own models.** Claude, OpenAI, Gemini, or any OpenAI-compatible server (Ollama, LM Studio, OpenRouter, vLLM). Users see which model is in use. The admin decides whether they can pick between models or always get the default.
- **Personalised.** It can use a user's top artists and recently played tracks so suggestions fit their taste.
- **Your own playlists.** Edit one of your Spotify playlists with AI, or use up to three as inspiration for a new one. Playlists you only open aren't added to your history.
- **Home page.** Signed-in users see new releases for their country, the most popular songs this year, trending Spotify playlists (popular and recently updated), and a feed of playlists other users shared anonymously.
- **Public landing page.** Visitors see Spotify's new releases and trending playlists before signing in.
- **Memberships (optional).** Free and paid plans with their own limits and features, paid through Stripe Checkout and the Stripe customer portal.
- **Fair use built in.** Daily and monthly limits on requests and tokens, with usage bars for users. Requests on a user's own key don't count.
- **Support.** A public support page with FAQs and a contact form. Signed-in users follow their requests there; admins answer from a support inbox.
- **Admin panel.**
  - Users: limits, plan, model access, disable, sign out everywhere, delete, and a detail page per user.
  - AI providers and models: discover, test, set the default.
  - Plans and payments log, community feed moderation, support inbox.
  - Audit log, sign-in methods, SMTP, site settings, and usage stats.
- **Privacy.** Users can download all their data as JSON, see and sign out their other devices, and delete their account. Deleting an account cancels its subscription first.
- **One container.** A FastAPI backend serves the React frontend. It runs on PostgreSQL, or SQLite for small installs.

## Spotify

### Sign-in and the Development Mode limits

Since February 2026, a new Spotify app runs in **Development Mode**:

- The app works for up to **5 Spotify accounts**, which you add under *User Management*.
- The app owner needs **Spotify Premium**.
- Spotify's own editorial playlists and the featured-playlists endpoint aren't available. Vibeify finds trending playlists through search instead.

Spotify grants *extended quota* only to registered businesses with a large user base. Vibeify supports two ways to connect, and you can turn on either or both:

| Method | How it works | Good for |
|---|---|---|
| **Continue with Spotify** (site app) | Uses your Spotify app's Client ID. One click for users. | You plus up to 5 others, or everyone if your app has extended quota |
| **Use my own Spotify app** | A guided setup: the user creates a free Spotify app, adds the redirect URI shown, and pastes the Client ID | Any number of users. Each user owns their own app (and needs Premium) |

Both use OAuth with PKCE, so signing in needs only a Client ID. When someone who isn't on the site app's user list tries "Continue with Spotify", Vibeify sends them to the own-app setup instead.

For larger sites, turn on Google and/or email accounts so people have an account first, then connect Spotify either way.

### Client secret (optional)

With the site app's **Client secret** set (Admin → Sign-in & Spotify), Vibeify fetches new releases and trending playlists as the app itself. This isn't personalised to anyone, and it lets the public landing page show music. Without the secret, the home page uses the viewer's own Spotify connection and the landing page uses an admin's.

The rows are cached in memory for 6 hours per country. Trending playlists must have at least 1,000 followers and songs added in the last 30 days. Playlists owned by anyone with an account here are always left out.

## Quick start (Docker Compose)

```bash
git clone git@github.com:<you>/vibeify.git && cd vibeify
cp .env.example .env
# edit .env: PUBLIC_URL, SECRET_KEY (openssl rand -base64 48), POSTGRES_PASSWORD, BOOTSTRAP_ADMINS
docker compose up -d --build
```

Open `PUBLIC_URL`, then sign in with an address or Spotify user ID listed in `BOOTSTRAP_ADMINS` to become an admin.
Or run `docker compose exec vibeify python -m app.cli make-admin <email-or-spotify-id>`.

Run it behind a reverse proxy with HTTPS (Caddy, Traefik, nginx, or a hosting platform's router). When `PUBLIC_URL` starts with `https://`, session cookies are marked `Secure`. Database migrations run when the container starts.

## Deploying to Render

`render.yaml` is a Render Blueprint: a Docker web service and a managed PostgreSQL database, both in Singapore.

1. In Render, choose **New → Blueprint** and pick this repository. Render asks once for:
   - `SECRET_KEY`: when moving an existing install, use the **same** value it already has.
   - `BOOTSTRAP_ADMINS`
2. Render builds the image, runs the migrations and starts the app. Every push to `main` deploys again.
3. To move data from a Docker Compose install, copy the database's **External** connection string from Render, then run:
   ```bash
   TARGET_DATABASE_URL='postgresql://…' scripts/migrate-to-render.sh
   ```
   The script stops the local app container, dumps the local database, restores it into Render, and compares row counts. Then restart the Render service.
4. Add your domain under the service's **Settings → Custom Domains**, and create the DNS records Render shows.
5. Update the redirect and webhook URLs to the new `PUBLIC_URL`: the Spotify app, the Google OAuth client and the Stripe webhook.

The app accepts the plain `postgresql://` URLs that Render and other hosts provide, and listens on `$PORT` when the host sets it.

### First-time setup in the admin panel

1. **AI models.** Add a provider and its API key.
   - Claude starts with Opus, Sonnet and Haiku.
   - For OpenAI and Gemini, use *Discover models*.
   - Test a model with the flask button, and star a default.
2. **Sign-in & Spotify.** Choose which sign-in methods are on.
   - For "Continue with Spotify", create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
   - Add the redirect URI shown in the panel (`{PUBLIC_URL}/api/auth/spotify/callback`), tick *Web API*, and paste the Client ID.
   - Optionally, paste the Client secret (see above).
3. **Google** (optional). Create an OAuth client of type *Web application* in Google Cloud Console. Use the redirect URI `{PUBLIC_URL}/api/auth/google/callback`.
4. **Email** (optional). Enter SMTP details and send a test email, then turn on email sign-up. Email also powers password resets and support notifications.
5. **Site & limits.** Set the site name and tagline, the default limits, the largest playlist size, whether users may add their own AI keys or choose the model, and how long to keep the audit log.
6. **Support** (optional). Choose where new support requests are emailed.

## Memberships and payments (optional)

Admin → **Plans & billing** sets up membership levels. Each plan can set its own:

- **Limits:** AI requests and tokens per 24 hours, tokens per month, and the largest playlist size.
- **Features:** editing your Spotify playlists, and using them as inspiration.
- **Models:** which AI models its members can use.

Mark one free plan as the **default**; everyone without a subscription gets it. Per-user overrides on the Users page take priority over plans, and plans take priority over the site defaults.

Payments go through **Stripe**:

1. Paste your Stripe secret key. Use the `sk_test_…` key first.
2. Save your paid plans. Vibeify creates the matching Stripe products and prices. Changing a price creates a new Stripe price and archives the old one; existing subscribers keep their price until they switch.
3. In Stripe → Developers → Webhooks, add `{PUBLIC_URL}/api/billing/webhook` with these events:
   - `checkout.session.completed`
   - `customer.subscription.created`, `.updated` and `.deleted`
   - for the payments log: `invoice.paid`, `invoice.payment_failed`, `charge.refunded`, `charge.dispute.created` and `charge.dispute.closed`

   Paste the signing secret (`whsec_…`) back into the panel.
4. Save the Stripe customer-portal settings once. Allow plan switching between your products there if you want members to change plans themselves.
5. Turn on **Sell paid plans**.

Members subscribe through Stripe Checkout and manage their card, invoices and cancellation in the Stripe customer portal. Webhooks keep each member's plan in sync. Each Stripe event is recorded once by its ID, so retried deliveries are never applied twice. A failed payment (`past_due`) keeps the plan while Stripe retries the card; a cancelled subscription drops back to the default plan.

## Records and auditing

- **Audit log** (Admin → Audit log):
  - sign-ins, failed sign-ins and sign-ups
  - account changes (passwords, Spotify, AI keys, data exports, deletions)
  - every admin change, with old and new values (secret values are only marked as changed)
  - billing events and support activity

  Entries keep the actor and target names after an account is deleted. Retention is set under Site & limits (default 365 days).
- **User detail page:** usage, membership with a Stripe link, sign-in methods, active sessions, payments, playlists, support requests and activity.
- **Community feed:** users choose per playlist whether to share it anonymously with signed-in users. Admins can hide any shared playlist.

## Configuration

Settings that the database needs, or that should live outside the admin panel, come from environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_URL` | `http://localhost:8000` | External URL with no trailing slash. Redirect URIs and email links are built from it |
| `SECRET_KEY` | *(required)* | At least 32 characters. Signs sessions and encrypts stored keys and tokens. **Never change it** on an existing database: stored secrets would become unreadable |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/vibeify.db` | `postgresql+asyncpg://user:pass@host/db` for PostgreSQL (set by `docker-compose.yml`) |
| `POSTGRES_PASSWORD` | *(required for Compose)* | Password for the Compose database |
| `POSTGRES_USER`, `POSTGRES_DB` | `vibeify` | Compose database user and name; set them only for a database created under other names |
| `BOOTSTRAP_ADMINS` | | Emails or Spotify user IDs that become admins when they sign in |
| `SPOTIFY_CLIENT_ID`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | | Optional. Used once, on first start, to set up the site; after that, change them in the admin panel |
| `TRUST_PROXY_HEADERS` | `true` | Use `X-Forwarded-For` for client IPs (rate limits, audit log) |
| `VIBEIFY_PORT` | `8000` | Host port in `docker-compose.yml` |

Everything else is set in the admin panel and stored in the database. Secrets there are encrypted with a key derived from `SECRET_KEY`.

Behind Cloudflare, the visitor's country for the public landing page comes from the `CF-IPCountry` header. Without it, the landing page uses the US.

### Protecting the admin panel with an SSO proxy (optional)

The admin panel already requires an admin account. If you also put `/admin` and `/api/admin` behind forward auth (Authentik, Authelia, oauth2-proxy, Cloudflare Access), the app copes: admin links do full page loads, and an expired proxy session sends the browser back through the proxy's login.

## Security notes

- **Passwords:** hashed with Argon2id.
- **Sessions:** random tokens in an HttpOnly, SameSite=Lax cookie. The server stores only a SHA-256 hash of each token. Disabling a user ends their sessions immediately.
- **CSRF:** state-changing API calls need a custom request header, which other sites can't send.
- **Stored secrets:** Spotify tokens and AI keys, the admin's and users', are encrypted at rest (Fernet).
- **OAuth:** state, PKCE verifier and nonce live in a short-lived, encrypted and signed cookie.
- **Email sign-up:** responses never reveal whether an address already has an account.
- **Rate limits:** sign-in, sign-up, password-reset, support and public discovery endpoints are rate limited (in memory, per process).
- **Caching:** the HTML page is never cached, so Back/Forward never reuses a page whose script files are gone after a deploy; hashed assets are cached for a year.

## Development

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
SECRET_KEY=dev-secret-key-at-least-32-characters-long alembic upgrade head
SECRET_KEY=dev-secret-key-at-least-32-characters-long uvicorn app.main:app --reload
pytest

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Or run the backend tests in a throwaway container:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app python:3.12-slim sh -c 'pip install -q -e ".[dev]" && pytest -q'
```

The tests never call real services. Spotify and Stripe are mocked with `respx`. The Anthropic and OpenAI SDKs use their own HTTP stack (`httpx2`), which respx can't see, so the `sdk_http` fixture stubs it.

Database changes: edit `backend/app/models.py`, then run `alembic revision --autogenerate -m "describe change"`.

### How it works

1. The AI suggests about 25% more songs than asked for, best first, as structured JSON with a reason for each song.
2. Each song is looked up on Spotify. The search is an exact `track:` / `artist:` query first, then a looser one, and results are fuzzy-matched on title and artist. Remasters, live versions and "feat." credits are ignored when matching.
3. The first *N* songs that match are kept. Songs that weren't found are shown but not saved.
4. Refining sends the current list and your instruction back to the model. Songs already matched aren't searched again.
5. Saving creates a private (or public) playlist, or replaces the contents of the one saved before.

On Claude models that support it, requests use Anthropic's server-side fallback. If the chosen model refuses a request, the API retries it on a fallback model, so users still get a playlist.

## License

No license has been chosen yet. The GitHub repository is private.
