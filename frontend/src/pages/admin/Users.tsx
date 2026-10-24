import { ChevronDown, Search, Shield, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useSession } from "../../session";
import { Button, Card, errorText, Field, formatDate, linkButton, Spinner, Toggle, useToast } from "../../ui";
import type { Provider } from "./Models";

export type AdminUser = {
  id: string; display_name: string; email: string | null; is_admin: boolean; is_disabled: boolean; created_at: string;
  last_login_at: string | null; sign_in_methods: string[]; spotify_user_id: string | null; spotify_app: "site" | "own" | null;
  daily_generation_limit: number | null; monthly_token_limit: number | null; allowed_model_ids: string[] | null; playlists: number; tokens_this_month: number;
  daily_token_limit: number | null; plan_id: string | null; plan_source: string | null; subscription_status: string | null;
};

export function UserEditor({ u, models, plans, onChanged, detailPage }: { u: AdminUser; models: { id: string; label: string }[];
  plans: { id: string; name: string }[]; onChanged: () => void; detailPage?: boolean }) {
  const { me } = useSession();
  const toast = useToast();
  const [daily, setDaily] = useState(u.daily_generation_limit?.toString() ?? "");
  const [monthly, setMonthly] = useState(u.monthly_token_limit?.toString() ?? "");
  const [dailyTokens, setDailyTokens] = useState(u.daily_token_limit?.toString() ?? "");
  const [allowed, setAllowed] = useState<string[] | null>(u.allowed_model_ids);
  const [busy, setBusy] = useState(false);
  const self = me?.id === u.id;
  const patch = async (body: object, ok = "Saved") => {
    setBusy(true);
    try { await api(`/admin/users/${u.id}`, { method: "PATCH", body }); toast(ok); onChanged(); } catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  };
  const n = (v: string) => (v === "" ? null : Number(v));
  const saveLimits = () => patch({
    clear_limits: true, daily_generation_limit: n(daily), daily_token_limit: n(dailyTokens), monthly_token_limit: n(monthly),
    ...(allowed === null ? { clear_allowed_models: true } : { allowed_model_ids: allowed }),
  });
  return (
    <div className="space-y-5 border-t border-white/5 bg-ink-850/50 px-4 py-5">
      <div className="flex flex-wrap gap-6">
        <Toggle checked={u.is_admin} disabled={self} onChange={(v) => patch({ is_admin: v })} label="Admin" />
        <Toggle checked={u.is_disabled} disabled={self} onChange={(v) => patch({ is_disabled: v })} label="Disabled" hint="Signs them out and blocks sign-in." />
      </div>
      {plans.length > 0 && (
        <Field label="Plan" hint={u.plan_source === "stripe" ? `Paid through Stripe (${u.subscription_status}). Changing it here is overwritten by the next Stripe update.` : "Gives this user a plan without payment."}>
          <select className="input" value={u.plan_id ?? ""} onChange={(e) => patch({ plan_id: e.target.value }, "Plan updated")}>
            <option value="">Default plan</option>
            {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="AI requests per day" hint="Blank = plan / site default"><input className="input" inputMode="numeric" value={daily} onChange={(e) => setDaily(e.target.value.replace(/\D/g, ""))} /></Field>
        <Field label="AI tokens per day" hint="Blank = plan / site default"><input className="input" inputMode="numeric" value={dailyTokens} onChange={(e) => setDailyTokens(e.target.value.replace(/\D/g, ""))} /></Field>
        <Field label="AI tokens per month" hint={`Blank = plan / site default · used ${u.tokens_this_month.toLocaleString()} this month`}><input className="input" inputMode="numeric" value={monthly} onChange={(e) => setMonthly(e.target.value.replace(/\D/g, ""))} /></Field>
      </div>
      <div>
        <Toggle checked={allowed === null} onChange={(v) => setAllowed(v ? null : models.map((m) => m.id))} label="Can use every enabled model" />
        {allowed !== null && (
          <div className="mt-3 flex flex-wrap gap-2">
            {models.map((m) => {
              const on = allowed.includes(m.id);
              return <button key={m.id} type="button" onClick={() => setAllowed(on ? allowed.filter((x) => x !== m.id) : [...allowed, m.id])}
                className={`rounded-full border px-3 py-1 text-xs ${on ? "border-mint/50 bg-mint/15 text-white" : "border-white/10 text-zinc-500"}`}>{m.label}</button>;
            })}
          </div>
        )}
      </div>
      <div className="flex flex-wrap justify-between gap-3">
        <div className="flex gap-2">
          <Button variant="primary" loading={busy} onClick={saveLimits}>Save limits</Button>
          {!detailPage && <Link to={`/admin/users/${u.id}`} className={linkButton("secondary")}>Details & activity</Link>}
        </div>
        {!self && <Button variant="danger" onClick={async () => {
          if (!confirm(`Delete ${u.display_name}'s account and history?${u.plan_source === "stripe" ? " Their Stripe subscription is cancelled immediately." : ""}`)) return;
          try { await api(`/admin/users/${u.id}`, { method: "DELETE" }); toast("User deleted"); onChanged(); } catch (e) { toast(errorText(e), "error"); }
        }}><Trash2 className="size-4" /> Delete user</Button>}
      </div>
    </div>
  );
}

export default function UsersPage() {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; users: AdminUser[] } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [plans, setPlans] = useState<{ id: string; name: string }[]>([]);
  const load = () => api(`/admin/users?${new URLSearchParams({ q, page: String(page) })}`).then(setData).catch((e) => toast(errorText(e), "error"));
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [q, page]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api<{ id: string; name: string }[]>("/admin/plans").then(setPlans).catch(() => {});
    api<Provider[]>("/admin/providers").then((ps) => setModels(ps.flatMap((p) => p.models.map((m) => ({ id: m.id, label: `${m.display_name}` }))))).catch(() => {});
  }, []);
  const pages = data ? Math.max(1, Math.ceil(data.total / 50)) : 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h2 className="text-2xl font-semibold text-white">Users</h2><p className="mt-1 text-sm text-zinc-400">{data ? `${data.total.toLocaleString()} accounts` : ""}</p></div>
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-500" />
          <input className="input pl-9" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="Name, email or Spotify ID" />
        </div>
      </div>
      {!data ? <Spinner /> : (
        <Card className="overflow-hidden !p-0">
          <ul className="divide-y divide-white/5">
            {data.users.map((u) => (
              <li key={u.id}>
                <button onClick={() => setOpen(open === u.id ? null : u.id)} className="flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-white/[0.03]">
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 truncate text-sm text-zinc-100">
                      {u.display_name}
                      {u.is_admin && <Shield className="size-3.5 text-violet" aria-label="Admin" />}
                      {u.is_disabled && <span className="rounded bg-red-500/20 px-1.5 text-[10px] uppercase text-red-300">Disabled</span>}
                    </p>
                    <p className="truncate text-xs text-zinc-500">{[u.email, u.spotify_user_id && `Spotify: ${u.spotify_user_id} (${u.spotify_app} app)`].filter(Boolean).join(" · ") || "No email or Spotify"}</p>
                  </div>
                  <div className="hidden text-right text-xs text-zinc-500 sm:block">
                    <p>{plans.find((p) => p.id === u.plan_id)?.name ?? "Default plan"} · {u.playlists} playlists · {u.tokens_this_month.toLocaleString()} tokens this month</p>
                    <p>Joined {formatDate(u.created_at)}{u.last_login_at ? ` · seen ${formatDate(u.last_login_at)}` : ""}</p>
                  </div>
                  <ChevronDown className={`size-4 text-zinc-500 transition ${open === u.id ? "rotate-180" : ""}`} />
                </button>
                {open === u.id && <UserEditor u={u} models={models} plans={plans} onChanged={load} />}
              </li>
            ))}
          </ul>
          {!data.users.length && <p className="p-6 text-sm text-zinc-500">No users found.</p>}
        </Card>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span className="text-zinc-400">Page {page} of {pages}</span>
          <Button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}
