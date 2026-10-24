import { Gauge } from "lucide-react";
import { Link } from "react-router-dom";
import type { Usage } from "../api";
import { useSession } from "../session";

const compact = (n: number) => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);

export function Meter({ label, used, limit, format = (n) => n.toLocaleString(), small }:
  { label: string; used: number; limit: number; format?: (n: number) => string; small?: boolean }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  const tone = pct >= 100 ? "bg-red-400" : pct >= 80 ? "bg-amber-300" : "bg-gradient-brand";
  return (
    <div>
      <div className={`mb-1 flex justify-between gap-3 ${small ? "text-xs" : "text-sm"}`}>
        <span className="text-zinc-400">{label}</span>
        <span className="tabular-nums text-zinc-200">{format(used)} <span className="text-zinc-500">/ {limit ? format(limit) : "unlimited"}</span></span>
      </div>
      <div className={`${small ? "h-1.5" : "h-2"} overflow-hidden rounded-full bg-ink-700`}>
        <div className={`h-full rounded-full transition-all ${tone}`} style={{ width: `${limit ? Math.max(pct, used ? 2 : 0) : 0}%` }} />
      </div>
    </div>
  );
}

/** Daily and monthly allowance on the site's AI keys. */
export function UsageMeters({ usage, small }: { usage: Usage; small?: boolean }) {
  return (
    <div className={small ? "space-y-2.5" : "grid gap-5 sm:grid-cols-3"}>
      <Meter small={small} label="Requests (24h)" used={usage.requests_today} limit={usage.daily_limit} />
      <Meter small={small} label="Tokens (24h)" used={usage.tokens_today} limit={usage.daily_token_limit} format={compact} />
      <Meter small={small} label="Tokens this month" used={usage.tokens_this_month} limit={usage.monthly_token_limit} format={compact} />
    </div>
  );
}

/** Compact card for the Create page. */
export function UsageCard() {
  const { me, config } = useSession();
  if (!me) return null;
  const u = me.usage;
  const near = [u.daily_limit && u.requests_today / u.daily_limit, u.daily_token_limit && u.tokens_today / u.daily_token_limit,
    u.monthly_token_limit && u.tokens_this_month / u.monthly_token_limit].some((x) => typeof x === "number" && x >= 0.8);
  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between text-sm">
        <span className="flex items-center gap-2 text-zinc-200"><Gauge className="size-4 text-aqua" /> Your AI allowance</span>
        <span className="text-xs text-zinc-500">{me.membership.plan?.name ?? ""}</span>
      </div>
      <UsageMeters usage={u} small />
      {near && config?.billing_enabled && <Link to="/pricing" className="mt-3 block text-xs text-aqua hover:underline">Running low? See plans →</Link>}
    </div>
  );
}
