import { Check, Copy, Plus, RefreshCw, Star, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, money, type BillingEventRow } from "../../api";
import { Button, Card, errorText, Field, formatDateTime, Notice, Spinner, Toggle, useToast } from "../../ui";
import { SecretInput, useSettings } from "./common";
import type { Provider } from "./Models";

type AdminPlan = {
  id: string; name: string; description: string; perks: string[]; price_cents: number; currency: string; interval: string;
  is_default: boolean; highlight: boolean; active: boolean; sort_order: number; members: number; purchasable: boolean;
  stripe_price_id: string | null; features: { edit_playlists: boolean; playlist_seeds: boolean };
  raw: { daily_generation_limit: number | null; daily_token_limit: number | null; monthly_token_limit: number | null; max_playlist_size: number | null; allowed_model_ids: string[] | null };
};

const EMPTY = { name: "", description: "", perks: "", price: "0", currency: "", interval: "month", is_default: false, active: true, highlight: false,
  sort_order: 0, daily_generation_limit: "", daily_token_limit: "", monthly_token_limit: "", max_playlist_size: "",
  allow_edit_playlists: true, allow_playlist_seeds: true, allowed_model_ids: null as string[] | null };
type Draft = typeof EMPTY;

const toDraft = (p: AdminPlan): Draft => ({
  name: p.name, description: p.description, perks: p.perks.join("\n"), price: (p.price_cents / 100).toString(), currency: p.currency,
  interval: p.interval, is_default: p.is_default, active: p.active, highlight: p.highlight, sort_order: p.sort_order,
  daily_generation_limit: p.raw.daily_generation_limit?.toString() ?? "", daily_token_limit: p.raw.daily_token_limit?.toString() ?? "",
  monthly_token_limit: p.raw.monthly_token_limit?.toString() ?? "", max_playlist_size: p.raw.max_playlist_size?.toString() ?? "",
  allow_edit_playlists: p.features.edit_playlists, allow_playlist_seeds: p.features.playlist_seeds, allowed_model_ids: p.raw.allowed_model_ids,
});
const num = (v: string) => (v.trim() === "" ? null : Number(v));
const toBody = (d: Draft) => ({
  name: d.name, description: d.description, perks: d.perks.split("\n").map((x) => x.trim()).filter(Boolean),
  price_cents: Math.round(Number(d.price || 0) * 100), currency: d.currency, interval: d.interval, is_default: d.is_default, active: d.active,
  highlight: d.highlight, sort_order: d.sort_order, daily_generation_limit: num(d.daily_generation_limit), daily_token_limit: num(d.daily_token_limit),
  monthly_token_limit: num(d.monthly_token_limit), max_playlist_size: num(d.max_playlist_size),
  allow_edit_playlists: d.allow_edit_playlists, allow_playlist_seeds: d.allow_playlist_seeds, allowed_model_ids: d.allowed_model_ids,
});

function PlanEditor({ initial, models, onSave, onCancel, saving }: { initial: Draft; models: { id: string; label: string }[];
  onSave: (d: Draft) => void; onCancel: () => void; saving: boolean }) {
  const [d, setD] = useState(initial);
  const set = <K extends keyof Draft>(k: K) => (v: Draft[K]) => setD({ ...d, [k]: v });
  const digits = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement>) => setD({ ...d, [k]: e.target.value.replace(/\D/g, "") });
  return (
    <div className="space-y-5 rounded-xl border border-white/10 bg-ink-850/60 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name"><input className="input" value={d.name} maxLength={60} onChange={(e) => set("name")(e.target.value)} placeholder="Pro" /></Field>
        <div className="grid grid-cols-[1fr_5rem_7rem] gap-2">
          <Field label="Price" hint="0 = free"><input className="input" inputMode="decimal" value={d.price} onChange={(e) => set("price")(e.target.value.replace(/[^\d.]/g, ""))} /></Field>
          <Field label="Currency"><input className="input uppercase" maxLength={3} value={d.currency} onChange={(e) => set("currency")(e.target.value.toLowerCase())} placeholder="usd" /></Field>
          <Field label="Every"><select className="input" value={d.interval} onChange={(e) => set("interval")(e.target.value)}><option value="month">month</option><option value="year">year</option></select></Field>
        </div>
        <div className="sm:col-span-2"><Field label="Description"><input className="input" value={d.description} maxLength={500} onChange={(e) => set("description")(e.target.value)} placeholder="For people who make a playlist every day" /></Field></div>
        <div className="sm:col-span-2"><Field label="Extra selling points" hint="One per line, shown above the automatic list of limits and features.">
          <textarea className="input min-h-20" value={d.perks} onChange={(e) => set("perks")(e.target.value)} placeholder={"Priority support\nEarly access to new features"} /></Field></div>
      </div>
      <div>
        <span className="label">Limits <span className="normal-case tracking-normal text-zinc-500">(blank = site default, 0 = unlimited)</span></span>
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Requests / 24h"><input className="input" inputMode="numeric" value={d.daily_generation_limit} onChange={digits("daily_generation_limit")} /></Field>
          <Field label="Tokens / 24h"><input className="input" inputMode="numeric" value={d.daily_token_limit} onChange={digits("daily_token_limit")} /></Field>
          <Field label="Tokens / month"><input className="input" inputMode="numeric" value={d.monthly_token_limit} onChange={digits("monthly_token_limit")} /></Field>
          <Field label="Max songs"><input className="input" inputMode="numeric" value={d.max_playlist_size} onChange={digits("max_playlist_size")} placeholder="5–100" /></Field>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Toggle checked={d.allow_edit_playlists} onChange={set("allow_edit_playlists")} label="Edit Spotify playlists" />
        <Toggle checked={d.allow_playlist_seeds} onChange={set("allow_playlist_seeds")} label="Playlists as inspiration" />
        <Toggle checked={d.is_default} onChange={set("is_default")} label="Default plan" hint="Everyone without a subscription gets this one." />
        <Toggle checked={d.active} onChange={set("active")} label="Offered" hint="Shown on the pricing page." />
        <Toggle checked={d.highlight} onChange={set("highlight")} label="Highlight as “Most popular”" />
      </div>
      <div>
        <Toggle checked={d.allowed_model_ids === null} onChange={(v) => set("allowed_model_ids")(v ? null : models.map((m) => m.id))} label="All enabled AI models" />
        {d.allowed_model_ids !== null && (
          <div className="mt-3 flex flex-wrap gap-2">
            {models.map((m) => {
              const on = d.allowed_model_ids!.includes(m.id);
              return <button key={m.id} type="button" onClick={() => set("allowed_model_ids")(on ? d.allowed_model_ids!.filter((x) => x !== m.id) : [...d.allowed_model_ids!, m.id])}
                className={`rounded-full border px-3 py-1 text-xs ${on ? "border-mint/50 bg-mint/15 text-white" : "border-white/10 text-zinc-500"}`}>{m.label}</button>;
            })}
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <Button variant="primary" loading={saving} disabled={!d.name.trim()} onClick={() => onSave(d)}>Save plan</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function StripeSettings() {
  const { settings, setSettings, save, saving } = useSettings();
  const toast = useToast();
  const [key, setKey] = useState("");
  const [hook, setHook] = useState("");
  const [test, setTest] = useState<{ ok: boolean; text: string; url?: string } | null>(null);
  const [copied, setCopied] = useState(false);
  if (!settings) return <Spinner />;
  const webhookUrl = `${window.location.origin}/api/billing/webhook`;
  const runTest = async () => {
    try { const r = await api<{ account: string; live: boolean; webhook_url: string }>("/admin/billing/test", { method: "POST" });
      setTest({ ok: true, text: `Connected to ${r.account} (${r.live ? "LIVE mode: real payments" : "test mode"})`, url: r.webhook_url }); }
    catch (e) { setTest({ ok: false, text: errorText(e) }); }
  };
  return (
    <Card title="Stripe">
      <div className="space-y-5">
        <Toggle checked={settings.billing_enabled} onChange={(v) => setSettings({ ...settings, billing_enabled: v })} label="Sell paid plans"
          hint="Shows the pricing page and lets members subscribe. Turn on once Stripe is connected and your plans are ready." />
        <div className="grid gap-4 sm:grid-cols-[1fr_1fr_6rem]">
          <Field label="Secret key" hint={<>Developers → API keys at <a className="text-aqua" href="https://dashboard.stripe.com/apikeys" target="_blank" rel="noreferrer">dashboard.stripe.com</a>. Use sk_test_… first.</>}>
            <SecretInput isSet={settings.stripe_secret_key} value={key} onChange={setKey} placeholder="sk_live_… or sk_test_…" /></Field>
          <Field label="Webhook signing secret" hint="From the webhook endpoint below (whsec_…).">
            <SecretInput isSet={settings.stripe_webhook_secret} value={hook} onChange={setHook} placeholder="whsec_…" /></Field>
          <Field label="Currency" hint="For new plans"><input className="input uppercase" maxLength={3} value={settings.billing_currency}
            onChange={(e) => setSettings({ ...settings, billing_currency: e.target.value.toLowerCase() })} /></Field>
        </div>
        <div className="rounded-xl border border-white/10 bg-ink-850 p-4 text-sm text-zinc-400">
          <p className="mb-2 text-zinc-200">Webhook setup (Developers → Webhooks → Add endpoint)</p>
          <div className="flex items-center gap-2 rounded-lg bg-ink-900 p-1.5 pl-3">
            <code className="min-w-0 flex-1 truncate text-mint">{webhookUrl}</code>
            <button type="button" onClick={async () => { await navigator.clipboard.writeText(webhookUrl); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
              className="inline-flex items-center gap-1 rounded-md bg-ink-700 px-2.5 py-1 text-xs text-zinc-100">{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} Copy</button>
          </div>
          <p className="mt-2">Events: <code>checkout.session.completed</code>, <code>customer.subscription.created</code>, <code>customer.subscription.updated</code>, <code>customer.subscription.deleted</code>.
            For the payments log also add <code>invoice.paid</code>, <code>invoice.payment_failed</code>, <code>charge.refunded</code>, <code>charge.dispute.created</code> and <code>charge.dispute.closed</code>.</p>
          <p className="mt-1">Also save your <a className="text-aqua" href="https://dashboard.stripe.com/settings/billing/portal" target="_blank" rel="noreferrer">customer portal settings</a> once, and allow switching between your plans' products there.</p>
        </div>
        {test && <Notice tone={test.ok ? "success" : "error"}>{test.text}</Notice>}
        <div className="flex gap-2">
          <Button variant="primary" loading={saving} onClick={() => save({ billing_enabled: settings.billing_enabled, billing_currency: settings.billing_currency,
            ...(key ? { stripe_secret_key: key } : {}), ...(hook ? { stripe_webhook_secret: hook } : {}) }).then((ok) => { if (ok) { setKey(""); setHook(""); } })}>Save</Button>
          <Button onClick={runTest}>Test connection</Button>
          <Button variant="ghost" onClick={async () => {
            try { const r = await api<{ warnings: string[] }>("/admin/plans/resync", { method: "POST" }); toast(r.warnings.length ? r.warnings.join(" ") : "Plans synced to Stripe", r.warnings.length ? "error" : "success"); }
            catch (e) { toast(errorText(e), "error"); }
          }}><RefreshCw className="size-4" /> Sync plans to Stripe</Button>
        </div>
      </div>
    </Card>
  );
}

export default function Billing() {
  const toast = useToast();
  const [plans, setPlans] = useState<AdminPlan[] | null>(null);
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [editing, setEditing] = useState<string | null>(null);   // plan id, or "new"
  const [saving, setSaving] = useState(false);
  const load = useCallback(() => api<AdminPlan[]>("/admin/plans").then(setPlans).catch((e) => toast(errorText(e), "error")), [toast]);
  useEffect(() => {
    load();
    api<Provider[]>("/admin/providers").then((ps) => setModels(ps.flatMap((p) => p.models.map((m) => ({ id: m.id, label: m.display_name }))))).catch(() => {});
  }, [load]);
  if (!plans) return <Spinner />;

  const save = async (id: string, d: Draft) => {
    setSaving(true);
    try {
      const r = await api<{ warning: string | null }>(id === "new" ? "/admin/plans" : `/admin/plans/${id}`, { method: id === "new" ? "POST" : "PATCH", body: toBody(d) });
      toast(r.warning ?? "Plan saved", r.warning ? "error" : "success"); setEditing(null); load();
    } catch (e) { toast(errorText(e), "error"); } finally { setSaving(false); }
  };
  const remove = async (p: AdminPlan) => {
    if (!confirm(`Delete the ${p.name} plan?`)) return;
    try { await api(`/admin/plans/${p.id}`, { method: "DELETE" }); load(); } catch (e) { toast(errorText(e), "error"); }
  };

  return (
    <div className="space-y-6">
      <div><h2 className="text-2xl font-semibold text-white">Plans & billing</h2>
        <p className="mt-1 text-sm text-zinc-400">Membership levels with their own limits and features. Paid plans are created in Stripe for you when you save.</p></div>
      {!plans.some((p) => p.is_default) && <Notice tone="warn">No default plan: people without a subscription get the site defaults with every feature on. Add a free plan and mark it default.</Notice>}
      <Card title="Plans" actions={editing !== "new" && <Button onClick={() => setEditing("new")}><Plus className="size-4" /> New plan</Button>}>
        <div className="space-y-3">
          {editing === "new" && <PlanEditor initial={EMPTY} models={models} saving={saving} onSave={(d) => save("new", d)} onCancel={() => setEditing(null)} />}
          {plans.map((p) => editing === p.id
            ? <PlanEditor key={p.id} initial={toDraft(p)} models={models} saving={saving} onSave={(d) => save(p.id, d)} onCancel={() => setEditing(null)} />
            : (
              <div key={p.id} className="flex flex-wrap items-center gap-4 rounded-xl border border-white/10 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-zinc-100">{p.name}
                    {p.is_default && <span className="rounded bg-ink-700 px-1.5 text-[10px] uppercase text-zinc-300">Default</span>}
                    {p.highlight && <Star className="size-3.5 fill-amber-300 text-amber-300" />}
                    {!p.active && <span className="rounded bg-ink-700 px-1.5 text-[10px] uppercase text-zinc-500">Hidden</span>}</p>
                  <p className="text-xs text-zinc-500">{p.price_cents ? `${money(p.price_cents, p.currency)} / ${p.interval}` : "Free"} · {p.members} member{p.members === 1 ? "" : "s"}
                    {p.price_cents > 0 && (p.stripe_price_id ? " · on Stripe" : " · not on Stripe yet")}</p>
                </div>
                <Button variant="ghost" onClick={() => setEditing(p.id)}>Edit</Button>
                <Button variant="ghost" onClick={() => remove(p)}><Trash2 className="size-4" /></Button>
              </div>
            ))}
          {!plans.length && editing !== "new" && <p className="text-sm text-zinc-500">No plans yet. Start with a free default plan, then add paid ones.</p>}
        </div>
      </Card>
      <StripeSettings />
      <BillingEvents />
    </div>
  );
}

function BillingEvents() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; events: BillingEventRow[] } | null>(null);
  useEffect(() => { api(`/admin/billing/events?page=${page}`).then(setData).catch(() => setData({ total: 0, events: [] })); }, [page]);
  if (!data) return null;
  const pages = Math.max(1, Math.ceil(data.total / 50));
  return (
    <section className="card overflow-hidden">
      <div className="px-5 pb-3 pt-5 sm:px-6"><h2 className="text-base font-semibold text-white">Payments log</h2>
        <p className="mt-1 text-xs text-zinc-500">Every Stripe event received. Repeats of the same event are ignored, so nothing is applied twice.</p></div>
      {!data.events.length ? <p className="px-6 pb-6 text-sm text-zinc-500">No events yet.</p> : (
        <ul className="divide-y divide-white/5 border-t border-white/5">
          {data.events.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-2.5 text-sm sm:px-6">
              <span className={`min-w-0 flex-1 ${/failed|dispute/.test(e.type) ? "text-amber-200" : e.amount_cents && e.amount_cents < 0 ? "text-red-300" : "text-zinc-200"}`}>{e.summary}</span>
              {e.user_id ? <Link to={`/admin/users/${e.user_id}`} className="truncate text-xs text-aqua hover:underline">{e.user_label || e.user_id}</Link>
                : <span className="font-mono text-xs text-zinc-500">{e.customer_id ?? "—"}</span>}
              <span className="shrink-0 text-xs text-zinc-500">{formatDateTime(e.stripe_created_at ?? e.received_at)}</span>
            </li>
          ))}
        </ul>
      )}
      {pages > 1 && <div className="flex items-center justify-center gap-3 border-t border-white/5 p-3 text-sm">
        <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button><span className="text-zinc-400">Page {page} of {pages}</span>
        <Button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button></div>}
    </section>
  );
}
