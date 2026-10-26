import { Check, Minus, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, money, type Plan } from "../api";
import { useSession } from "../session";
import { Button, errorText, formatDate, linkButton, Notice, Spinner, useToast } from "../ui";

const compact = (n: number) => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
const limitText = (n: number, unit: string) => (n ? `${compact(n)} ${unit}` : `Unlimited ${unit}`);

export async function openBillingPortal(toast: (t: string, tone?: "error") => void) {
  try { window.location.assign((await api<{ url: string }>("/billing/portal", { method: "POST" })).url); }
  catch (e) { toast(errorText(e), "error"); }
}

export default function Pricing() {
  const { me } = useSession();
  const toast = useToast();
  const [params] = useSearchParams();
  const [data, setData] = useState<{ billing_enabled: boolean; plans: Plan[] } | null>(null);
  const [busy, setBusy] = useState("");
  useEffect(() => { api("/plans").then(setData).catch((e) => toast(errorText(e), "error")); }, [toast]);
  if (!data) return <Spinner />;


  const current = me?.membership.plan?.id;
  const subscribed = me && ["active", "trialing", "past_due"].includes(me.membership.status ?? "") && me.membership.source === "stripe";
  const needsSpotify = !!me && !me.spotify && !subscribed;   // a plan is no use without Spotify, so checkout requires it
  const choose = async (p: Plan) => {
    if (subscribed) return openBillingPortal(toast);
    setBusy(p.id);
    try { window.location.assign((await api<{ url: string }>("/billing/checkout", { body: { plan_id: p.id } })).url); }
    catch (e) { toast(errorText(e), "error"); setBusy(""); }
  };

  return (
    <div>
      <div className="mx-auto max-w-2xl text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white">Plans</h1>
        <p className="mt-3 text-zinc-400">More AI, bigger playlists, and tools for editing your own Spotify playlists.</p>
      </div>
      {params.get("billing") === "cancelled" && <div className="mx-auto mt-6 max-w-xl"><Notice>Checkout was cancelled. Nothing was charged.</Notice></div>}
      {!data.plans.length && <p className="mt-10 text-center text-zinc-500">No plans are set up yet.</p>}
      {needsSpotify && data.plans.some((p) => p.purchasable) && <div className="mx-auto mt-6 max-w-xl"><Notice tone="warn">
        Connect your Spotify account before choosing a plan. Vibeify makes your playlists there.</Notice></div>}

      <div className="mx-auto mt-10 grid max-w-5xl gap-5" style={{ gridTemplateColumns: `repeat(auto-fit, minmax(15rem, 1fr))` }}>
        {data.plans.map((p) => {
          const isCurrent = current === p.id;
          const promo = subscribed ? null : p.promotion;
          const discounted = promo?.percent_off ? Math.round(p.price_cents * (100 - promo.percent_off) / 100) : null;
          return (
            <div key={p.id} className={`card relative flex flex-col p-6 ${p.highlight ? "border-aqua/50 shadow-2xl shadow-aqua/10" : ""}`}>
              {p.highlight && <span className="bg-gradient-brand absolute -top-3 left-6 rounded-full px-3 py-0.5 text-xs font-semibold text-ink-950">Most popular</span>}
              <h2 className="text-lg font-semibold text-white">{p.name}</h2>
              <p className="mt-1 min-h-10 text-sm text-zinc-400">{p.description}</p>
              <p className="mt-4 text-4xl font-bold text-white">
                {discounted !== null && <span className="mr-2 text-2xl font-medium text-zinc-500 line-through">{money(p.price_cents, p.currency)}</span>}
                {p.price_cents ? money(discounted ?? p.price_cents, p.currency) : "Free"}
                {p.price_cents > 0 && <span className="text-base font-normal text-zinc-500"> / {p.interval}</span>}</p>
              {promo && (
                <p className="mt-3 flex items-start gap-2 rounded-lg border border-mint/30 bg-mint/10 px-3 py-2 text-sm text-mint">
                  <Sparkles className="mt-0.5 size-4 shrink-0" />
                  <span><b>{promo.summary}</b>{promo.first_subscription_only ? " for new subscribers" : ""}
                    {promo.ends_at ? <span className="text-mint/70"> · ends {formatDate(promo.ends_at)}</span> : null}</span>
                </p>
              )}
              <ul className="mt-6 flex-1 space-y-2.5 text-sm">
                {p.perks.map((x) => <li key={x} className="flex gap-2 text-zinc-200"><Check className="mt-0.5 size-4 shrink-0 text-mint" />{x}</li>)}
                <li className="flex gap-2 text-zinc-300"><Check className="mt-0.5 size-4 shrink-0 text-mint" />{limitText(p.limits.daily_requests, "AI requests a day")}</li>
                <li className="flex gap-2 text-zinc-300"><Check className="mt-0.5 size-4 shrink-0 text-mint" />{limitText(p.limits.monthly_tokens, "AI tokens a month")}</li>
                <li className="flex gap-2 text-zinc-300"><Check className="mt-0.5 size-4 shrink-0 text-mint" />Playlists up to {p.limits.max_playlist_size} songs</li>
                {p.models.length > 0 && <li className="flex gap-2 text-zinc-300"><Check className="mt-0.5 size-4 shrink-0 text-mint" />
                  {p.model_choice ? <span>Choose your AI: {p.models.join(", ")}</span> : <span>Powered by {p.models[0]}</span>}</li>}
                {([["edit_playlists", "Edit your Spotify playlists with AI"], ["playlist_seeds", "Use your playlists as inspiration"]] as const).map(([k, label]) => (
                  <li key={k} className={`flex gap-2 ${p.features[k] ? "text-zinc-300" : "text-zinc-600"}`}>
                    {p.features[k] ? <Check className="mt-0.5 size-4 shrink-0 text-mint" /> : <Minus className="mt-0.5 size-4 shrink-0" />}{label}</li>
                ))}
              </ul>
              <div className="mt-6">
                {isCurrent ? <span className={linkButton("secondary", "w-full cursor-default")}>Your plan</span>
                  : !me ? <Link to="/signin?next=/pricing" className={linkButton(p.highlight ? "primary" : "secondary", "w-full")}>Sign in to start</Link>
                  : p.purchasable && needsSpotify ? <Link to="/connect-spotify?next=/pricing" className={linkButton("spotify", "w-full")}>Connect Spotify first</Link>
                  : p.purchasable ? <Button variant={p.highlight ? "primary" : "secondary"} className="w-full" loading={busy === p.id} onClick={() => choose(p)}>
                      {subscribed ? "Switch plan" : promo?.trial_days ? `Start ${promo.trial_days}-day free trial` : `Get ${p.name}`}</Button>
                  : p.is_default ? (subscribed ? <Button className="w-full" onClick={() => openBillingPortal(toast)}>Cancel subscription</Button> : null)
                  : <span className="block text-center text-xs text-zinc-500">Not available yet</span>}
              </div>
            </div>
          );
        })}
      </div>
      {data.billing_enabled && <p className="mt-8 text-center text-xs text-zinc-500">Payments are handled securely by Stripe. Cancel any time from your account.
        Have a promo code? Enter it on the payment page.</p>}
    </div>
  );
}
