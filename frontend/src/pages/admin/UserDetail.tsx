import { ArrowLeft, ExternalLink, EyeOff, LogOut, Monitor, Shield, Smartphone } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type AuditEntry, type BillingEventRow } from "../../api";
import { Button, Card, errorText, formatDate, formatDateTime, Notice, Spinner, timeAgo, useToast } from "../../ui";
import { describeAgent } from "../Account";
import { AuditRow } from "./Audit";
import type { Provider } from "./Models";
import { UserEditor, type AdminUser } from "./Users";

type Detail = {
  id: string; display_name: string; email: string | null; email_verified: boolean; avatar_url: string | null; is_admin: boolean;
  is_disabled: boolean; has_password: boolean; created_at: string; last_login_at: string | null;
  identities: { provider: string; subject: string; created_at: string }[];
  spotify: null | { spotify_user_id: string; display_name: string; app: "site" | "own"; client_id: string; connected_at: string };
  membership: { plan: string | null; plan_id: string | null; plan_source: string | null; status: string | null; period_end: string | null;
    cancel_at_period_end: boolean; stripe_customer_id: string | null; stripe_subscription_id: string | null; stripe_url: string | null };
  limits: { daily_generation_limit: number | null; daily_token_limit: number | null; monthly_token_limit: number | null; allowed_model_ids: string[] | null };
  usage: { month_requests: number; month_tokens: number; month_own_key_requests: number; all_requests: number; all_tokens: number; playlists: number };
  sessions: { created_at: string; last_seen_at: string; expires_at: string; ip: string; user_agent: string }[];
  playlists: { id: string; title: string; created_at: string; tracks: number; spotify_url: string | null; shared: boolean; community_hidden: boolean }[];
  activity: AuditEntry[];
  payments: BillingEventRow[];
  support: { id: string; number: number; subject: string; status: string; updated_at: string }[];
};

// A card whose rows run edge to edge, with a padded title.
function ListCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="card overflow-hidden"><h2 className="px-5 pb-3 pt-5 text-base font-semibold text-white sm:px-6">{title}</h2>{children}</section>;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div><p className="text-xs text-zinc-500">{label}</p><p className="text-lg font-semibold tabular-nums text-white">{value}</p></div>;
}

export default function UserDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const [u, setU] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [plans, setPlans] = useState<{ id: string; name: string }[]>([]);
  const load = useCallback(() => api<Detail>(`/admin/users/${id}`).then(setU).catch((e) => {
    if (e.status === 404) nav("/admin/users", { replace: true });   // e.g. just deleted
    else setError(errorText(e));
  }), [id, nav]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api<{ id: string; name: string }[]>("/admin/plans").then(setPlans).catch(() => {});
    api<Provider[]>("/admin/providers").then((ps) => setModels(ps.flatMap((p) => p.models.map((m) => ({ id: m.id, label: m.display_name }))))).catch(() => {});
  }, []);
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!u) return <Spinner />;

  const m = u.membership;
  const editable: AdminUser = {
    id: u.id, display_name: u.display_name, email: u.email, is_admin: u.is_admin, is_disabled: u.is_disabled, created_at: u.created_at,
    last_login_at: u.last_login_at, sign_in_methods: u.identities.map((i) => i.provider), spotify_user_id: u.spotify?.spotify_user_id ?? null,
    spotify_app: u.spotify?.app ?? null, ...u.limits, plan_id: m.plan_id, plan_source: m.plan_source, subscription_status: m.status,
    playlists: u.usage.playlists, tokens_this_month: u.usage.month_tokens,
  };
  const signOut = async () => {
    try { const r = await api<{ sessions: number }>(`/admin/users/${u.id}/sign-out`, { body: {} }); toast(`Ended ${r.sessions} session(s)`); load(); }
    catch (e) { toast(errorText(e), "error"); }
  };
  const hide = async (gid: string, hidden: boolean) => {
    try { await api(`/admin/community/${gid}`, { method: "PATCH", body: { hidden } }); load(); } catch (e) { toast(errorText(e), "error"); }
  };

  return (
    <div className="space-y-6">
      <Link to="/admin/users" className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white"><ArrowLeft className="size-4" /> All users</Link>
      <div className="flex flex-wrap items-center gap-4">
        {u.avatar_url ? <img src={u.avatar_url} alt="" className="size-14 rounded-full object-cover" />
          : <span className="grid size-14 place-items-center rounded-full bg-gradient-brand text-xl font-bold text-ink-950">{u.display_name.slice(0, 1).toUpperCase()}</span>}
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-2xl font-semibold text-white">{u.display_name}
            {u.is_admin && <Shield className="size-4 text-violet" aria-label="Admin" />}
            {u.is_disabled && <span className="rounded bg-red-500/20 px-1.5 text-xs uppercase text-red-300">Disabled</span>}</h2>
          <p className="text-sm text-zinc-400">{u.email ?? "No email"}{u.email && (u.email_verified ? " · verified" : " · not verified")} · joined {formatDate(u.created_at)}
            {u.last_login_at && ` · last sign-in ${timeAgo(u.last_login_at)}`}</p>
          <p className="font-mono text-xs text-zinc-600">{u.id}</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Usage">
          <div className="grid grid-cols-3 gap-4">
            <Stat label="AI requests this month" value={u.usage.month_requests.toLocaleString()} />
            <Stat label="Tokens this month" value={u.usage.month_tokens.toLocaleString()} />
            <Stat label="Own-key requests" value={u.usage.month_own_key_requests.toLocaleString()} />
            <Stat label="Requests all time" value={u.usage.all_requests.toLocaleString()} />
            <Stat label="Tokens all time" value={u.usage.all_tokens.toLocaleString()} />
            <Stat label="Playlists" value={u.usage.playlists.toLocaleString()} />
          </div>
        </Card>
        <Card title="Membership" actions={m.stripe_url && <a href={m.stripe_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-aqua hover:underline">Stripe <ExternalLink className="size-3.5" /></a>}>
          <p className="text-lg font-semibold text-white">{m.plan ?? "Default plan"}</p>
          <p className="text-sm text-zinc-400">{m.plan_source === "stripe" ? `Paid · ${m.status}${m.period_end ? ` · ${m.cancel_at_period_end ? "ends" : "renews"} ${formatDate(m.period_end)}` : ""}`
            : m.plan_source === "admin" ? "Given by an admin" : m.status ? `Subscription ${m.status}` : "No subscription"}</p>
          {m.stripe_customer_id && <p className="mt-2 font-mono text-xs text-zinc-600">{m.stripe_customer_id}{m.stripe_subscription_id && ` · ${m.stripe_subscription_id}`}</p>}
          {m.status === "past_due" && <div className="mt-3"><Notice tone="warn">Their last payment failed; Stripe is retrying.</Notice></div>}
        </Card>
        <Card title="Sign-in methods">
          <ul className="space-y-2 text-sm">
            {u.identities.map((i) => <li key={i.provider + i.subject} className="flex justify-between gap-3"><span className="capitalize text-zinc-200">{i.provider}</span>
              <span className="truncate text-zinc-500">{i.subject} · {formatDate(i.created_at)}</span></li>)}
            {u.has_password && !u.identities.some((i) => i.provider === "email") && <li className="text-zinc-400">Password set</li>}
          </ul>
          {u.spotify && <p className="mt-4 border-t border-white/5 pt-3 text-sm text-zinc-400">Spotify <span className="text-zinc-200">{u.spotify.display_name || u.spotify.spotify_user_id}</span> through the {u.spotify.app === "site" ? "site's app" : `user's own app (${u.spotify.client_id.slice(0, 6)}…)`}, since {formatDate(u.spotify.connected_at)}</p>}
        </Card>
        <Card title="Active sessions" actions={u.sessions.length > 0 && <Button className="!py-1.5" onClick={signOut}><LogOut className="size-4" /> Sign out everywhere</Button>}>
          {!u.sessions.length ? <p className="text-sm text-zinc-500">Not signed in anywhere.</p> : (
            <ul className="divide-y divide-white/5">
              {u.sessions.map((s, i) => {
                const a = describeAgent(s.user_agent);
                const Icon = a.mobile ? Smartphone : Monitor;
                return <li key={i} className="flex items-center gap-3 py-2"><Icon className="size-4 shrink-0 text-zinc-500" />
                  <div className="min-w-0"><p className="text-sm text-zinc-200">{a.label}</p>
                    <p className="truncate text-xs text-zinc-500">{s.ip} · since {formatDate(s.created_at)} · active {timeAgo(s.last_seen_at)}</p></div></li>;
              })}
            </ul>
          )}
        </Card>
      </div>

      <ListCard title="Access, plan & limits"><UserEditor u={editable} models={models} plans={plans} onChanged={load} detailPage /></ListCard>

      {u.payments.length > 0 && (
        <ListCard title="Payments & billing events">
          <ul className="divide-y divide-white/5">
            {u.payments.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                <span className={p.type.includes("failed") || p.type.includes("dispute") ? "text-amber-200" : "text-zinc-200"}>{p.summary}</span>
                <span className="shrink-0 text-xs text-zinc-500">{formatDateTime(p.stripe_created_at ?? p.received_at)}</span>
              </li>
            ))}
          </ul>
        </ListCard>
      )}

      {u.support.length > 0 && (
        <ListCard title="Support requests">
          <ul className="divide-y divide-white/5">
            {u.support.map((t) => (
              <li key={t.id}><Link to={`/admin/support/${t.id}`} className="flex items-center gap-3 px-5 py-2.5 text-sm hover:bg-white/[0.03] sm:px-6">
                <span className="font-mono text-xs text-zinc-500">#{t.number}</span><span className="min-w-0 flex-1 truncate text-zinc-200">{t.subject}</span>
                <span className="text-xs capitalize text-zinc-500">{t.status} · {timeAgo(t.updated_at)}</span></Link></li>
            ))}
          </ul>
        </ListCard>
      )}

      <ListCard title="Recent playlists">
        {!u.playlists.length ? <p className="p-5 text-sm text-zinc-500">No playlists yet.</p> : (
          <ul className="divide-y divide-white/5">
            {u.playlists.map((g) => (
              <li key={g.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <div className="min-w-0 flex-1"><p className="truncate text-zinc-200">{g.title || "Untitled"}</p>
                  <p className="text-xs text-zinc-500">{g.tracks} songs · {formatDate(g.created_at)}{g.shared && (g.community_hidden ? " · hidden from community" : " · shared on community")}</p></div>
                {g.shared && <button onClick={() => hide(g.id, !g.community_hidden)} title={g.community_hidden ? "Show on community feed" : "Hide from community feed"}
                  className="rounded-lg p-1.5 text-zinc-500 hover:bg-white/5 hover:text-white"><EyeOff className="size-4" /></button>}
                {g.spotify_url && <a href={g.spotify_url} target="_blank" rel="noreferrer" className="rounded-lg p-1.5 text-zinc-500 hover:bg-white/5 hover:text-white"><ExternalLink className="size-4" /></a>}
              </li>
            ))}
          </ul>
        )}
      </ListCard>

      <ListCard title="Activity">
        {!u.activity.length ? <p className="p-5 text-sm text-zinc-500">Nothing recorded yet.</p>
          : <ul className="divide-y divide-white/5">{u.activity.map((e) => <AuditRow key={e.id} e={e} />)}</ul>}
      </ListCard>
    </div>
  );
}
