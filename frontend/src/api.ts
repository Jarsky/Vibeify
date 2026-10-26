// Thin fetch wrapper: JSON in/out, cookie session, CSRF header, readable errors.
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      credentials: "same-origin",
      headers: { "X-Requested-With": "vibeify", ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    // A reverse proxy guarding /admin (e.g. Authentik forward auth) redirects expired sessions to its login page,
    // which fetch can't follow cross-origin. Reload the page so the browser does the login.
    if (path.startsWith("/admin")) { window.location.assign(window.location.pathname); }
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d: any) => d.msg).join("; ")
      : res.status === 502 || res.status === 504 ? "The server took too long or is unavailable. Try again."
      : `Request failed (${res.status})`;
    throw new ApiError(msg, res.status);
  }
  return data as T;
}

function safeJson(t: string) { try { return JSON.parse(t); } catch { return null; } }

export const spotifyStartUrl = (opts: { mode: "login" | "link"; clientId?: string; returnTo?: string }) => {
  const q = new URLSearchParams({ mode: opts.mode });
  if (opts.clientId) q.set("client_id", opts.clientId);
  if (opts.returnTo) q.set("return_to", opts.returnTo);
  return `/api/auth/spotify/start?${q}`;
};

const oidcStartUrl = (provider: "google" | "apple") => (opts: { mode?: "login" | "link"; returnTo?: string } = {}) => {
  const q = new URLSearchParams({ mode: opts.mode ?? "login" });
  if (opts.returnTo) q.set("return_to", opts.returnTo);
  return `/api/auth/${provider}/start?${q}`;
};
export const googleStartUrl = oidcStartUrl("google");
export const appleStartUrl = oidcStartUrl("apple");

// ── types ────────────────────────────────────────────────────────────────────
export type SiteConfig = {
  site_name: string; site_tagline: string; signup_open: boolean;
  sign_in: { spotify_site_app: boolean; spotify_own_app: boolean; google: boolean; apple: boolean; email: boolean };
  spotify_redirect_uri: string; allow_user_llm_keys: boolean; allow_model_choice: boolean; community_feed: boolean; support_enabled: boolean; max_playlist_size: number; billing_enabled: boolean;
  provider_kinds: Record<string, string>; signed_in: boolean;
};

export type ModelOption = { id: string; label: string; kind: string; own_key: boolean; is_default: boolean };

export type Me = {
  id: string; display_name: string; email: string | null; email_verified: boolean; avatar_url: string | null;
  is_admin: boolean; has_password: boolean; created_at: string; sign_in_methods: string[];
  identities: { provider: string; email: string | null; linked_at: string }[];
  spotify: null | { spotify_user_id: string; display_name: string; uses_site_app: boolean; client_id: string; connected_at: string };
  llm_keys: { kind: string; model_id: string; base_url: string | null; key_hint: string }[];
  models: ModelOption[];
  usage: Usage;
  membership: Membership;
};

export type Usage = { requests_today: number; daily_limit: number; tokens_today: number; daily_token_limit: number;
  tokens_this_month: number; monthly_token_limit: number };
export type Membership = {
  plan: null | { id: string; name: string; price_cents: number; currency: string; interval: string };
  status: string | null; period_end: string | null; cancel_at_period_end: boolean; source: string | null;
  has_billing_account: boolean; features: { edit_playlists: boolean; playlist_seeds: boolean }; max_playlist_size: number;
};
export type Plan = {
  id: string; name: string; description: string; perks: string[]; price_cents: number; currency: string; interval: string;
  is_default: boolean; highlight: boolean; purchasable: boolean;
  limits: { daily_requests: number; daily_tokens: number; monthly_tokens: number; max_playlist_size: number };
  features: { edit_playlists: boolean; playlist_seeds: boolean };
};

export const money = (cents: number, currency: string) =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase(), minimumFractionDigits: cents % 100 ? 2 : 0 }).format(cents / 100);

export type SpotifyTrack = { id: string; uri: string; name: string; artists: string[]; album: string; image: string | null;
  url: string | null; duration_ms: number; explicit: boolean };
export type Track = { title: string; artist: string; reason: string; spotify: SpotifyTrack | null };
export type Message = { role: "user" | "assistant"; content: string };

export type GenerationSummary = { id: string; title: string; description: string; model_label: string; created_at: string;
  updated_at: string; count: number; matched: number; spotify_playlist_url: string | null; cover: string | null;
  shared: boolean; spotify_public: boolean; imported: boolean };
export type Generation = GenerationSummary & { request: any; messages: Message[]; tracks: Track[] };
export type SpotifyPlaylist = { id: string; name: string; description: string; image: string | null; total: number; url: string | null; public: boolean | null };

// ── discover (home page) ─────────────────────────────────────────────────────
export type Album = { id: string; name: string; artists: string[]; image: string | null; release_date: string; type: string;
  tracks: number; url: string | null };
export type IdeaPlaylist = { id: string; name: string; description: string; image: string | null; owner: string; tracks: number;
  theme: string; url: string | null; followers: number; updated: string };
export type CommunityPlaylist = { id: string; title: string; description: string; tracks: number; covers: string[]; artists: string[];
  created_at: string; mine: boolean; url: string | null };
export type DiscoverRows = { connected: boolean; country: string | null; errors: Record<string, string>;
  rows: { new_releases?: Album[]; trending?: (SpotifyTrack & { popularity: number })[]; inspiration?: IdeaPlaylist[] } };

// ── audit ────────────────────────────────────────────────────────────────────
export type AuditEntry = { id: number; created_at: string; actor_id: string | null; actor_label: string; action: string;
  target_type: string | null; target_id: string | null; target_label: string; details: Record<string, any>; ip: string };
export type BillingEventRow = { id: string; type: string; user_id: string | null; user_label?: string; customer_id: string | null;
  summary: string; amount_cents: number | null; currency: string | null; stripe_created_at: string | null; received_at: string };

// ── support ──────────────────────────────────────────────────────────────────
export type SupportMessage = { from: "user" | "admin"; body: string; at: string; author: string };
export type SupportTicket = { id: string; number: number; category: string; subject: string; status: "open" | "waiting" | "closed";
  created_at: string; updated_at: string; messages: SupportMessage[] };
export const SUPPORT_CATEGORIES: Record<string, string> = {
  bug: "Something isn't working", account: "Account & sign-in", billing: "Billing & plans",
  spotify: "Spotify connection", feedback: "Feedback & ideas", other: "Something else",
};
