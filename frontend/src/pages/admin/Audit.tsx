import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AuditEntry } from "../../api";
import { Button, Card, errorText, formatDateTime, Spinner, useToast } from "../../ui";

const ACTIONS: Record<string, string> = {
  "auth.login": "Signed in", "auth.login_failed": "Failed sign-in", "auth.login_blocked": "Blocked sign-in (disabled)",
  "auth.password_reset": "Reset password by email",
  "account.create": "Created account", "account.delete": "Deleted account", "account.export": "Downloaded their data",
  "account.password_changed": "Changed password", "account.password_set": "Set a password",
  "account.spotify_connect": "Connected Spotify", "account.spotify_disconnect": "Disconnected Spotify",
  "account.ai_key_set": "Saved own AI key", "account.ai_key_removed": "Removed own AI key",
  "account.sign_out_others": "Signed out other devices",
  "admin.user.update": "Changed user", "admin.user.delete": "Deleted user", "admin.user.sign_out": "Signed user out everywhere",
  "admin.settings.update": "Changed settings",
  "admin.provider.create": "Added AI provider", "admin.provider.update": "Changed AI provider", "admin.provider.delete": "Removed AI provider",
  "admin.model.create": "Added AI model", "admin.model.update": "Changed AI model", "admin.model.delete": "Removed AI model",
  "admin.plan.create": "Created plan", "admin.plan.update": "Changed plan", "admin.plan.delete": "Deleted plan",
  "admin.community.hide": "Hid playlist from community", "admin.community.show": "Restored playlist to community",
  "admin.support.reply": "Replied to support request", "admin.support.status": "Changed support request status",
  "support.ticket_created": "Sent a support request",
  "billing.checkout_started": "Started checkout", "billing.subscription": "Subscription changed",
  "billing.payment_failed": "Payment failed", "billing.refund": "Refund issued",
  "billing.dispute_opened": "Dispute opened", "billing.dispute_closed": "Dispute closed",
};

const CATEGORIES = [["", "All"], ["admin", "Admin changes"], ["auth", "Sign-ins"], ["account", "Account"], ["billing", "Billing"], ["support", "Support"]] as const;

const TONE: Record<string, string> = { support: "bg-sky-400/10 text-sky-300", admin: "bg-violet/15 text-violet", auth: "bg-aqua/10 text-aqua", account: "bg-mint/10 text-mint", billing: "bg-amber-400/10 text-amber-300" };
const ALERTS = new Set(["auth.login_failed", "auth.login_blocked", "billing.payment_failed", "billing.dispute_opened", "admin.user.delete", "account.delete"]);

const human = (k: string) => k.replace(/_/g, " ").replace(/^is /, "");
const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : Array.isArray(v) ? (v.length ? v.join(", ") : "none") : typeof v === "object" ? JSON.stringify(v) : String(v));

export function AuditDetails({ details }: { details: Record<string, any> }) {
  const { changes, ...rest } = details;
  const parts: string[] = [];
  if (changes) for (const [k, v] of Object.entries(changes)) parts.push(Array.isArray(v) ? `${human(k)}: ${show(v[0])} → ${show(v[1])}` : `${human(k)}: ${show(v)}`);
  for (const [k, v] of Object.entries(rest)) if (k !== "user_agent") parts.push(`${human(k)}: ${show(v)}`);
  if (!parts.length) return null;
  return <p className="mt-0.5 break-words text-xs text-zinc-500">{parts.join(" · ")}</p>;
}

export function AuditRow({ e, linkUsers = true }: { e: AuditEntry; linkUsers?: boolean }) {
  const cat = e.action.split(".")[0];
  const who = e.actor_label || (e.actor_id ? "(deleted user)" : "System");
  const userLink = (id: string | null, label: string) =>
    linkUsers && id ? <Link to={`/admin/users/${id}`} className="text-zinc-200 hover:underline">{label}</Link> : <span className="text-zinc-200">{label}</span>;
  const sameUser = e.actor_id && e.actor_id === e.target_id;
  return (
    <li className="flex gap-3 px-4 py-3">
      <span className={`mt-0.5 h-fit shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase ${TONE[cat] ?? "bg-white/5 text-zinc-400"}`}>{cat}</span>
      <div className="min-w-0 flex-1 text-sm">
        <p className={ALERTS.has(e.action) ? "text-amber-200" : "text-zinc-400"}>
          {userLink(e.actor_id, who)} <span>{(ACTIONS[e.action] ?? e.action).toLowerCase()}</span>
          {e.target_label && !sameUser && <> · {e.target_type === "user" ? userLink(e.target_id, e.target_label) : <span className="text-zinc-200">{e.target_label}</span>}</>}
        </p>
        <AuditDetails details={e.details} />
      </div>
      <div className="shrink-0 text-right text-xs text-zinc-500">
        <p>{formatDateTime(e.created_at)}</p>
        {e.ip && <p className="font-mono">{e.ip}</p>}
      </div>
    </li>
  );
}

export default function AuditPage() {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; entries: AuditEntry[] } | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api(`/admin/audit?${new URLSearchParams({ q, category, page: String(page) })}`).then(setData)
      .catch((e) => toast(errorText(e), "error")), 250);
    return () => clearTimeout(t);
  }, [q, category, page, toast]);
  const pages = data ? Math.max(1, Math.ceil(data.total / 50)) : 1;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-white">Audit log</h2>
          <p className="mt-1 text-sm text-zinc-400">Admin changes, sign-ins, account and billing events. Retention is set under Site & limits.</p>
        </div>
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-500" />
          <input className="input pl-9" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="Email, action or IP" />
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {CATEGORIES.map(([value, label]) => (
          <button key={value} onClick={() => { setCategory(value); setPage(1); }}
            className={`rounded-full border px-3 py-1 text-xs transition ${category === value ? "border-aqua/50 bg-aqua/10 text-white" : "border-white/10 text-zinc-400 hover:text-white"}`}>{label}</button>
        ))}
      </div>
      {!data ? <Spinner /> : (
        <Card className="overflow-hidden !p-0">
          <ul className="divide-y divide-white/5">{data.entries.map((e) => <AuditRow key={e.id} e={e} />)}</ul>
          {!data.entries.length && <p className="p-6 text-sm text-zinc-500">Nothing recorded{q || category ? " that matches" : " yet"}.</p>}
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
