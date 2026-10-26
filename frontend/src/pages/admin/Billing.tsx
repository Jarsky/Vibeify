import { Check, Copy, Plus, RefreshCw, Sparkles, Star, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, money, type BillingEventRow, type Promotion } from "../../api";
import { Button, Card, errorText, Field, formatDateTime, Notice, Spinner, Toggle, useToast } from "../../ui";
import { SecretInput, useSettings } from "./common";
import type { Provider } from "./Models";

type AdminPlan = {
  id: string; name: string; description: string; perks: string[]; price_cents: number; currency: string; interval: string;
  is_default: boolean; highlight: boolean; active: boolean; sort_order: number; members: number; purchasable: boolean;
  stripe_price_id: string | null; features: { edit_playlists: boolean; playlist_seeds: boolean };
  raw: { daily_generation_limit: number | null; daily_token_limit: number | null; monthly_token_limit: number | null; max_playlist_size: number | null; allowed_model_ids: string[] | null;
    default_model_id: string | null; allow_model_choice: boolean | null };
};

const EMPTY = { name: "", description: "", perks: "", price: "0", currency: "", interval: "month", is_default: false, active: true, highlight: false,
  sort_order: 0, daily_generation_limit: "", daily_token_limit: "", monthly_token_limit: "", max_playlist_size: "",
  allow_edit_playlists: true, allow_playlist_seeds: true, allowed_model_ids: null as string[] | null,
  default_model_id: "", allow_model_choice: "site" as "site" | "yes" | "no" };
type Draft = typeof EMPTY;

const toDraft = (p: AdminPlan): Draft => ({
  name: p.name, description: p.description, perks: p.perks.join("\n"), price: (p.price_cents / 100).toString(), currency: p.currency,
  interval: p.interval, is_default: p.is_default, active: p.active, highlight: p.highlight, sort_order: p.sort_order,
  daily_generation_limit: p.raw.daily_generation_limit?.toString() ?? "", daily_token_limit: p.raw.daily_token_limit?.toString() ?? "",
  monthly_token_limit: p.raw.monthly_token_limit?.toString() ?? "", max_playlist_size: p.raw.max_playlist_size?.toString() ?? "",
  allow_edit_playlists: p.features.edit_playlists, allow_playlist_seeds: p.features.playlist_seeds, allowed_model_ids: p.raw.allowed_model_ids,
  default_model_id: p.raw.default_model_id ?? "",
  allow_model_choice: p.raw.allow_model_choice === null ? "site" : p.raw.allow_model_choice ? "yes" : "no",
});
const num = (v: string) => (v.trim() === "" ? null : Number(v));
const toBody = (d: Draft) => ({
  name: d.name, description: d.description, perks: d.perks.split("\n").map((x) => x.trim()).filter(Boolean),
  price_cents: Math.round(Number(d.price || 0) * 100), currency: d.currency, interval: d.interval, is_default: d.is_default, active: d.active,
  highlight: d.highlight, sort_order: d.sort_order, daily_generation_limit: num(d.daily_generation_limit), daily_token_limit: num(d.daily_token_limit),
  monthly_token_limit: num(d.monthly_token_limit), max_playlist_size: num(d.max_playlist_size),
  allow_edit_playlists: d.allow_edit_playlists, allow_playlist_seeds: d.allow_playlist_seeds, allowed_model_ids: d.allowed_model_ids,
  default_model_id: d.default_model_id && (!d.allowed_model_ids || d.allowed_model_ids.includes(d.default_model_id)) ? d.default_model_id : null,
  allow_model_choice: d.allow_model_choice === "site" ? null : d.allow_model_choice === "yes",
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
        <span className="label">AI models</span>
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
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Field label="Members start on" hint="Used for every playlist unless they may choose another.">
            <select className="input" value={d.default_model_id} onChange={(e) => set("default_model_id")(e.target.value)}>
              <option value="">The site's default model</option>
              {models.filter((m) => !d.allowed_model_ids || d.allowed_model_ids.includes(m.id)).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </Field>
          <Field label="Members may choose a model" hint="Pick from the models allowed above.">
            <select className="input" value={d.allow_model_choice} onChange={(e) => set("allow_model_choice")(e.target.value as Draft["allow_model_choice"])}>
              <option value="site">Follow the site setting</option>
              <option value="yes">Yes</option>
              <option value="no">No, always the model above</option>
            </select>
          </Field>
        </div>
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
          <p className="mt-2">Events: <code>checkout.session.completed</code>, <code>customer.subscription.created</code>, <code>customer.subscription.updated</code>, <code>customer.subscription.deleted</code>, <code>checkout.session.expired</code>.
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
          }}><RefreshCw className="size-4" /> Sync plans & codes to Stripe</Button>
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
      <Promotions plans={plans} />
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

type AdminPromotion = Promotion & { code: string | null; starts_at: string | null; max_redemptions: number | null; redemptions: number;
  reserved: number; active: boolean; status: string; on_stripe: boolean; warning: string | null };

const PROMO_EMPTY = { name: "", code: "", plan_ids: null as string[] | null, trial_days: "", percent_off: "", duration: "once",
  duration_months: "", starts_at: "", ends_at: "", max_redemptions: "", first_subscription_only: true, active: true };
type PromoDraft = typeof PROMO_EMPTY;
const toLocal = (iso: string | null) => (iso ? new Date(iso).toISOString().slice(0, 10) : "");
const promoDraft = (p: AdminPromotion): PromoDraft => ({
  name: p.name, code: p.code ?? "", plan_ids: p.plan_ids, trial_days: p.trial_days?.toString() ?? "", percent_off: p.percent_off?.toString() ?? "",
  duration: p.duration, duration_months: p.duration_months?.toString() ?? "", starts_at: toLocal(p.starts_at), ends_at: toLocal(p.ends_at),
  max_redemptions: p.max_redemptions?.toString() ?? "", first_subscription_only: p.first_subscription_only, active: p.active,
});
const promoBody = (d: PromoDraft) => ({
  name: d.name, code: d.code.trim() || null, plan_ids: d.plan_ids, trial_days: d.code.trim() ? null : num(d.trial_days), percent_off: num(d.percent_off),
  duration: d.duration, duration_months: d.duration === "repeating" ? num(d.duration_months) : null,
  starts_at: d.starts_at ? new Date(`${d.starts_at}T00:00:00`).toISOString() : null,
  ends_at: d.ends_at ? new Date(`${d.ends_at}T23:59:59`).toISOString() : null,
  max_redemptions: num(d.max_redemptions), first_subscription_only: d.first_subscription_only, active: d.active,
});

function PromotionEditor({ initial, plans, onSave, onCancel, saving }: { initial: PromoDraft; plans: AdminPlan[];
  onSave: (d: PromoDraft) => void; onCancel: () => void; saving: boolean }) {
  const [d, setD] = useState(initial);
  const set = <K extends keyof PromoDraft>(k: K) => (v: PromoDraft[K]) => setD({ ...d, [k]: v });
  const digits = (k: keyof PromoDraft) => (e: React.ChangeEvent<HTMLInputElement>) => setD({ ...d, [k]: e.target.value.replace(/\D/g, "") });
  const paid = plans.filter((p) => p.price_cents > 0);
  return (
    <div className="space-y-5 rounded-xl border border-white/10 bg-ink-850/60 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" hint="Shown to customers, e.g. “Launch special”."><input className="input" value={d.name} maxLength={80} onChange={(e) => set("name")(e.target.value)} /></Field>
        <Field label="Code" hint="Typed on Stripe's payment page; discounts only. Leave blank to apply automatically to everyone who qualifies.">
          <input className="input font-mono uppercase" value={d.code} maxLength={40} onChange={(e) => set("code")(e.target.value.replace(/[^A-Za-z0-9_-]/g, "").toUpperCase())} placeholder="SUMMER25" /></Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Free trial (days)" hint={d.code ? "Not possible with a code" : undefined}>
          <input className="input" inputMode="numeric" value={d.code ? "" : d.trial_days} onChange={digits("trial_days")} placeholder="e.g. 30" disabled={!!d.code} /></Field>
        <Field label="% off"><input className="input" inputMode="numeric" value={d.percent_off} onChange={digits("percent_off")} placeholder="e.g. 50" /></Field>
        <Field label="Discount lasts"><select className="input" value={d.duration} onChange={(e) => set("duration")(e.target.value)} disabled={!d.percent_off}>
          <option value="once">First payment</option><option value="repeating">Some months</option><option value="forever">Forever</option></select></Field>
        {d.duration === "repeating" && d.percent_off
          ? <Field label="Months"><input className="input" inputMode="numeric" value={d.duration_months} onChange={digits("duration_months")} /></Field> : <div />}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Starts" hint="Blank = now"><input className="input" type="date" value={d.starts_at} onChange={(e) => set("starts_at")(e.target.value)} /></Field>
        <Field label="Ends" hint="Blank = no end date"><input className="input" type="date" value={d.ends_at} onChange={(e) => set("ends_at")(e.target.value)} /></Field>
        <Field label="Max uses" hint="Blank = unlimited"><input className="input" inputMode="numeric" value={d.max_redemptions} onChange={digits("max_redemptions")} /></Field>
      </div>
      <div>
        <Toggle checked={d.plan_ids === null} onChange={(v) => set("plan_ids")(v ? null : paid.map((p) => p.id))} label="All paid plans" />
        {d.plan_ids !== null && (
          <div className="mt-3 flex flex-wrap gap-2">
            {paid.map((p) => {
              const on = d.plan_ids!.includes(p.id);
              return <button key={p.id} type="button" onClick={() => set("plan_ids")(on ? d.plan_ids!.filter((x) => x !== p.id) : [...d.plan_ids!, p.id])}
                className={`rounded-full border px-3 py-1 text-xs ${on ? "border-mint/50 bg-mint/15 text-white" : "border-white/10 text-zinc-500"}`}>{p.name}</button>;
            })}
          </div>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Toggle checked={d.first_subscription_only} onChange={set("first_subscription_only")} label="First subscription only"
          hint="People who have subscribed before can't use it." />
        <Toggle checked={d.active} onChange={set("active")} label="Active" hint="Turn off to pause it." />
      </div>
      <div className="flex gap-2">
        <Button variant="primary" loading={saving} disabled={!d.name.trim() || (d.code ? !d.percent_off : !d.trial_days && !d.percent_off)} onClick={() => onSave(d)}>Save promotion</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function Promotions({ plans }: { plans: AdminPlan[] }) {
  const toast = useToast();
  const [rows, setRows] = useState<AdminPromotion[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const load = useCallback(() => api<AdminPromotion[]>("/admin/promotions").then(setRows).catch((e) => toast(errorText(e), "error")), [toast]);
  useEffect(() => { load(); }, [load]);
  if (!rows) return null;
  const planNames = (ids: string[] | null) => (ids ? ids.map((id) => plans.find((p) => p.id === id)?.name ?? "deleted plan").join(", ") : "all paid plans");
  const save = async (id: string, d: PromoDraft) => {
    setSaving(true);
    try {
      const r = await api<AdminPromotion>(id === "new" ? "/admin/promotions" : `/admin/promotions/${id}`, { method: id === "new" ? "POST" : "PATCH", body: promoBody(d) });
      toast(r.warning ?? (r.code ? `Saved. ${r.code} works on Stripe's payment page.` : "Promotion saved"), r.warning ? "error" : "success"); setEditing(null); load();
    } catch (e) { toast(errorText(e), "error"); } finally { setSaving(false); }
  };
  const remove = async (p: AdminPromotion) => {
    if (!confirm(`Delete “${p.name}”? People already subscribed keep their discount.`)) return;
    try { await api(`/admin/promotions/${p.id}`, { method: "DELETE" }); load(); } catch (e) { toast(errorText(e), "error"); }
  };
  return (
    <Card title="Promotions" actions={editing !== "new" && <Button onClick={() => setEditing("new")}><Plus className="size-4" /> New promotion</Button>}>
      <p className="-mt-1 mb-4 text-sm text-zinc-400">Automatic promotions (free trials and discounts) show on the pricing page and apply at checkout.
        Code promotions become Stripe promotion codes that customers type on Stripe's payment page; Stripe enforces their limits.
        Stripe hides its code box when an automatic discount already applies. Changing a discount doesn't affect people already using it.</p>
      <div className="space-y-3">
        {editing === "new" && <PromotionEditor initial={PROMO_EMPTY} plans={plans} saving={saving} onSave={(d) => save("new", d)} onCancel={() => setEditing(null)} />}
        {rows.map((p) => editing === p.id
          ? <PromotionEditor key={p.id} initial={promoDraft(p)} plans={plans} saving={saving} onSave={(d) => save(p.id, d)} onCancel={() => setEditing(null)} />
          : (
            <div key={p.id} className="flex flex-wrap items-center gap-4 rounded-xl border border-white/10 px-4 py-3">
              <Sparkles className={`size-5 shrink-0 ${p.status === "Running" ? "text-mint" : "text-zinc-600"}`} />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-zinc-100">{p.name}
                  {p.code ? <><code className="rounded bg-ink-700 px-1.5 text-xs text-mint">{p.code}</code>
                    {!p.on_stripe && <span className="rounded bg-amber-400/15 px-1.5 text-[10px] uppercase text-amber-200" title="Save it again or use “Sync plans & codes to Stripe”">Not on Stripe</span>}</>
                    : <span className="rounded bg-ink-700 px-1.5 text-[10px] uppercase text-zinc-300">Automatic</span>}
                  {p.status !== "Running" && <span className="rounded bg-ink-700 px-1.5 text-[10px] uppercase text-zinc-500">{p.status}</span>}</p>
                <p className="text-xs text-zinc-500">{p.summary} · {planNames(p.plan_ids)} · used {p.redemptions}{p.max_redemptions ? ` of ${p.max_redemptions}` : ""}{p.reserved ? ` (+${p.reserved} in checkout)` : ""}
                  {p.ends_at ? ` · ends ${formatDateTime(p.ends_at)}` : ""}</p>
              </div>
              <Button variant="ghost" onClick={() => setEditing(p.id)}>Edit</Button>
              <Button variant="ghost" onClick={() => remove(p)}><Trash2 className="size-4" /></Button>
            </div>
          ))}
        {!rows.length && editing !== "new" && <p className="text-sm text-zinc-500">No promotions yet.</p>}
      </div>
    </Card>
  );
}
