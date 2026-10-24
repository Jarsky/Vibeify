import { CreditCard, Download, KeyRound, LogOut, Monitor, Smartphone, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, googleStartUrl, money } from "../api";
import { useSession } from "../session";
import { Button, Card, errorText, Field, formatDate, linkButton, Notice, timeAgo, useToast } from "../ui";
import { openBillingPortal } from "./Pricing";
import { GoogleIcon, SpotifyIcon } from "./SignInOptions";
import { UsageMeters } from "./Usage";

function PlanCard() {
  const { me, config, refresh } = useSession();
  const toast = useToast();
  const [params] = useSearchParams();
  useEffect(() => {   // after Checkout the webhook may land a moment later: poll briefly
    if (params.get("billing") !== "success") return;
    let n = 0;
    const t = setInterval(() => { refresh(); if (++n >= 5) clearInterval(t); }, 2500);
    return () => clearInterval(t);
  }, [params, refresh]);
  if (!me || !config?.billing_enabled) return null;
  const m = me.membership;
  const live = ["active", "trialing", "past_due"].includes(m.status ?? "") && m.source === "stripe";
  return (
    <Card title="Plan" actions={<Link to="/pricing" className="text-sm text-aqua hover:underline">Compare plans</Link>}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-lg font-semibold text-white">{m.plan?.name ?? "Free"}
            {m.plan && m.plan.price_cents > 0 && <span className="ml-2 text-sm font-normal text-zinc-400">{money(m.plan.price_cents, m.plan.currency)} / {m.plan.interval}</span>}</p>
          <p className="text-sm text-zinc-400">
            {m.status === "past_due" ? "Your last payment failed. Update your card to keep your plan."
              : live && m.period_end ? `${m.cancel_at_period_end ? "Ends" : "Renews"} ${formatDate(m.period_end)}`
              : m.source === "admin" ? "Set by the site admin" : "No subscription"}
          </p>
        </div>
        <div className="flex gap-2">
          {m.has_billing_account && <Button onClick={() => openBillingPortal(toast)}><CreditCard className="size-4" /> Manage billing</Button>}
          {!live && <Link to="/pricing" className={linkButton("primary")}>Upgrade</Link>}
        </div>
      </div>
    </Card>
  );
}

type Device = { id: string; current: boolean; created_at: string; last_seen_at: string; ip: string; user_agent: string };

// "Chrome on Windows" from a user agent; good enough to recognise your own devices.
export function describeAgent(ua: string) {
  const browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /iPhone|iPad/.test(ua) ? "iOS" : /Android/.test(ua) ? "Android" : /Windows/.test(ua) ? "Windows"
    : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return { label: os ? `${browser} on ${os}` : browser, mobile: /iPhone|Android|Mobile/.test(ua) };
}

function Devices() {
  const toast = useToast();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => api<Device[]>("/me/sessions").then(setDevices).catch(() => setDevices([]));
  useEffect(() => { load(); }, []);
  if (!devices) return null;
  const others = devices.filter((d) => !d.current).length;
  return (
    <Card title="Signed-in devices" actions={others > 0 && <Button loading={busy} className="!py-1.5" onClick={async () => {
      setBusy(true);
      try { const r = await api<{ sessions: number }>("/me/sessions/sign-out-others", { body: {} }); toast(`Signed out ${r.sessions} other device(s)`); load(); }
      catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
    }}><LogOut className="size-4" /> Sign out others</Button>}>
      <ul className="divide-y divide-white/5">
        {devices.map((d) => {
          const a = describeAgent(d.user_agent);
          const Icon = a.mobile ? Smartphone : Monitor;
          return (
            <li key={d.id} className="flex items-center gap-3 py-2.5">
              <Icon className="size-5 shrink-0 text-zinc-500" />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-zinc-100">{a.label} {d.current && <span className="ml-1 rounded bg-mint/15 px-1.5 text-[10px] uppercase text-mint">This device</span>}</p>
                <p className="truncate text-xs text-zinc-500">{[d.ip, `signed in ${formatDate(d.created_at)}`, `active ${timeAgo(d.last_seen_at)}`].filter(Boolean).join(" · ")}</p>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-zinc-500">Don't recognise one? Sign out the others and change your password.</p>
    </Card>
  );
}

async function downloadExport(toast: ReturnType<typeof useToast>) {
  try {
    const res = await fetch("/api/me/export", { credentials: "same-origin" });
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "account-export.json";
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) { toast(errorText(e), "error"); }
}

const ERRORS: Record<string, string> = {
  spotify_in_use: "That Spotify account is already connected to a different account here.",
  google_in_use: "That Google account is already used by a different account here.",
};

const KEY_HELP: Record<string, { url: string; placeholder: string; model: string }> = {
  anthropic: { url: "https://console.anthropic.com/settings/keys", placeholder: "sk-ant-…", model: "claude-opus-5-5" },
  openai: { url: "https://platform.openai.com/api-keys", placeholder: "sk-…", model: "" },
  gemini: { url: "https://aistudio.google.com/apikey", placeholder: "AIza…", model: "" },
  openai_compatible: { url: "", placeholder: "Key (if the server needs one)", model: "" },
};

function OwnKeys() {
  const { me, config, refresh } = useSession();
  const toast = useToast();
  const [kind, setKind] = useState("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [modelId, setModelId] = useState(KEY_HELP.anthropic.model);
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  if (!me || !config?.allow_user_llm_keys) return null;
  const help = KEY_HELP[kind];
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true);
    try {
      await api("/me/llm-keys", { method: "PUT", body: { kind, api_key: apiKey, model_id: modelId, base_url: kind === "openai_compatible" ? baseUrl : null } });
      setApiKey(""); await refresh(); toast("Key saved and checked");
    } catch (err) { toast(errorText(err), "error"); } finally { setBusy(false); }
  };
  const remove = async (k: string) => { await api(`/me/llm-keys/${k}`, { method: "DELETE" }); await refresh(); };
  return (
    <Card title={<span className="flex items-center gap-2"><KeyRound className="size-4 text-aqua" /> Your own AI keys</span>}>
      <p className="mb-5 text-sm text-zinc-400">Optional. Requests on your own key don't count towards the site's limits; your provider bills you directly.
        Keys are encrypted and never shown again.</p>
      {me.llm_keys.length > 0 && (
        <ul className="mb-5 divide-y divide-white/5 rounded-xl border border-white/10">
          {me.llm_keys.map((k) => (
            <li key={k.kind} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
              <div><p className="text-zinc-100">{config.provider_kinds[k.kind] ?? k.kind}</p>
                <p className="text-xs text-zinc-500">{k.model_id} · {k.key_hint}</p></div>
              <Button variant="ghost" onClick={() => remove(k.kind)}><Trash2 className="size-4" /></Button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
        <Field label="Provider">
          <select className="input" value={kind} onChange={(e) => { setKind(e.target.value); setModelId(KEY_HELP[e.target.value].model); }}>
            {Object.entries(config.provider_kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Model" hint={kind === "openai" ? "e.g. the model name shown in your OpenAI dashboard" : kind === "gemini" ? "e.g. a Gemini model name from AI Studio" : undefined}>
          <input className="input" required value={modelId} onChange={(e) => setModelId(e.target.value)} placeholder="Model name" />
        </Field>
        {kind === "openai_compatible" && (
          <div className="sm:col-span-2"><Field label="Base URL" hint="For example an Ollama, LM Studio, OpenRouter or vLLM endpoint ending in /v1">
            <input className="input" required value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" /></Field></div>
        )}
        <div className="sm:col-span-2">
          <Field label="API key" hint={help.url && <>Get one from <a className="text-aqua" href={help.url} target="_blank" rel="noreferrer">{new URL(help.url).hostname}</a></>}>
            <input className="input font-mono" type="password" autoComplete="off" required={kind !== "openai_compatible"} minLength={8} value={apiKey}
              onChange={(e) => setApiKey(e.target.value)} placeholder={help.placeholder} />
          </Field>
        </div>
        <div className="sm:col-span-2"><Button variant="primary" loading={busy}>Check & save key</Button></div>
      </form>
    </Card>
  );
}

export default function Account() {
  const { me, config, refresh } = useSession();
  const toast = useToast();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [name, setName] = useState(me?.display_name ?? "");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState("");
  if (!me || !config) return null;
  const error = params.get("error");

  const run = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key);
    try { await fn(); await refresh(); if (ok) toast(ok); } catch (e) { toast(errorText(e), "error"); } finally { setBusy(""); }
  };
  const has = (m: string) => me.sign_in_methods.includes(m);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Account</h1>
        <p className="mt-1 text-zinc-400">Member since {formatDate(me.created_at)}</p>
      </div>
      {error && <Notice tone="error">{ERRORS[error] ?? "Something went wrong."}</Notice>}
      {params.get("billing") === "success" && <Notice tone="success">Thanks for subscribing! Your plan updates as soon as Stripe confirms the payment (usually a few seconds).</Notice>}

      <Card title="Profile">
        <form className="flex gap-3" onSubmit={(e) => { e.preventDefault(); run("name", () => api("/me", { method: "PATCH", body: { display_name: name } }), "Saved"); }}>
          <input className="input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          <Button loading={busy === "name"} disabled={!name.trim() || name === me.display_name}>Save</Button>
        </form>
        {me.email && <p className="mt-3 text-sm text-zinc-400">Email: <span className="text-zinc-200">{me.email}</span> {me.email_verified && <span className="text-mint">· verified</span>}</p>}
      </Card>

      <Card title="Spotify">
        {me.spotify ? (
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-full bg-[#1ed760]/15 text-[#1ed760]"><SpotifyIcon /></span>
              <div>
                <p className="text-zinc-100">{me.spotify.display_name || me.spotify.spotify_user_id}</p>
                <p className="text-xs text-zinc-500">{me.spotify.uses_site_app ? `Through ${config.site_name}'s app` : `Through your own app (${me.spotify.client_id.slice(0, 6)}…)`}</p>
              </div>
            </div>
            <div className="flex gap-2">
              <Link to="/connect-spotify" className={linkButton("secondary")}>Reconnect</Link>
              <Button variant="danger" loading={busy === "spotify"} onClick={() => run("spotify", () => api("/me/spotify", { method: "DELETE" }), "Spotify disconnected")}>Disconnect</Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-zinc-400">Not connected. You need Spotify to make playlists.</p>
            <Link to="/connect-spotify" className={linkButton("spotify")}><SpotifyIcon /> Connect</Link>
          </div>
        )}
      </Card>

      <PlanCard />

      <Card title="Usage">
        <UsageMeters usage={me.usage} />
        <p className="mt-4 text-xs text-zinc-500">Each new playlist and each chat refinement is one request. Daily figures cover the last 24 hours;
          monthly figures reset on the 1st.{config.allow_user_llm_keys ? " Requests on your own AI key don't count." : ""}</p>
      </Card>

      <OwnKeys />

      <Card title="Sign-in">
        <ul className="mb-5 flex flex-wrap gap-2">
          {me.sign_in_methods.map((m) => <li key={m} className="rounded-full border border-white/10 bg-ink-850 px-3 py-1 text-sm capitalize text-zinc-300">{m}</li>)}
        </ul>
        {config.sign_in.google && !has("google") && (
          <a href={googleStartUrl("/account")} className={linkButton("secondary", "mb-5")}><GoogleIcon /> Link Google</a>
        )}
        {me.email ? (
          <form className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]" onSubmit={(e) => { e.preventDefault();
            run("pw", () => api("/me/password", { body: { current_password: current, new_password: next } }), "Password updated").then(() => { setCurrent(""); setNext(""); }); }}>
            {me.has_password && <input className="input" type="password" autoComplete="current-password" placeholder="Current password" value={current} onChange={(e) => setCurrent(e.target.value)} />}
            <input className={`input ${me.has_password ? "" : "sm:col-span-2"}`} type="password" autoComplete="new-password" placeholder={me.has_password ? "New password" : "Set a password (10+ characters)"} value={next} onChange={(e) => setNext(e.target.value)} />
            <Button loading={busy === "pw"} disabled={next.length < 10}>{me.has_password ? "Change" : "Set password"}</Button>
          </form>
        ) : <p className="text-sm text-zinc-500">{config.sign_in.google ? "Link Google to add an email address and a backup way to sign in." : "You sign in with Spotify."}</p>}
      </Card>

      <Devices />

      <Card title="Your data">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-zinc-400">Download everything stored about your account (profile, playlists, AI usage, sign-in activity) as a JSON file.
            Keys, tokens and your password are never included.</p>
          <Button className="shrink-0" onClick={() => downloadExport(toast)}><Download className="size-4" /> Download my data</Button>
        </div>
      </Card>

      <Card title="Delete account">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-zinc-400">Deletes your account, history and keys here{me.membership.status && ["active", "trialing", "past_due"].includes(me.membership.status)
            ? ", and cancels your subscription straight away" : ""}. Playlists already saved to Spotify stay there.</p>
          <Button variant="danger" loading={busy === "del"} onClick={() => {
            if (confirm("Delete your account permanently? This can't be undone."))
              run("del", async () => { await api("/me", { method: "DELETE" }); nav("/"); });
          }}><Trash2 className="size-4" /> Delete</Button>
        </div>
      </Card>
    </div>
  );
}
