import { ArrowLeft, Mail, Search, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, SUPPORT_CATEGORIES, type SupportTicket } from "../../api";
import { Button, Card, errorText, Field, formatDateTime, Notice, Spinner, timeAgo, Toggle, useToast } from "../../ui";
import { Thread } from "../Support";
import { useSettings } from "./common";

type AdminTicket = SupportTicket & { name: string; email: string; user_id: string | null; context: Record<string, any> };
type ListItem = Omit<AdminTicket, "messages"> & { message_count: number; last_from: "user" | "admin" | null; preview: string };

const TABS = [["open", "Open"], ["waiting", "Waiting on them"], ["closed", "Closed"], ["", "All"]] as const;
const TONE: Record<string, string> = { open: "bg-aqua/10 text-aqua", waiting: "bg-mint/15 text-mint", closed: "bg-white/5 text-zinc-400" };

function SupportSettings() {
  const { settings, setSettings, save, saving } = useSettings();
  if (!settings) return null;
  return (
    <Card title="Settings">
      <div className="space-y-4">
        <Toggle checked={settings.support_enabled} onChange={(v) => setSettings({ ...settings, support_enabled: v })} label="Contact form on the support page"
          hint="Off leaves the FAQ but hides the form." />
        <div className="max-w-md"><Field label="Email new requests to" hint="Needs SMTP on the Email page. Blank = only here. People also get a copy of replies by email when SMTP works.">
          <input className="input" type="email" value={settings.support_email} onChange={(e) => setSettings({ ...settings, support_email: e.target.value })} placeholder="support@example.com" /></Field></div>
        <Button variant="primary" loading={saving} onClick={() => save({ support_enabled: settings.support_enabled, support_email: settings.support_email })}>Save</Button>
      </div>
    </Card>
  );
}

export default function SupportInbox() {
  const toast = useToast();
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [data, setData] = useState<{ total: number; counts: Record<string, number>; tickets: ListItem[] } | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api(`/admin/support?${new URLSearchParams({ status, q })}`).then(setData).catch((e) => toast(errorText(e), "error")), 200);
    return () => clearTimeout(t);
  }, [status, q, toast]);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h2 className="text-2xl font-semibold text-white">Support</h2><p className="mt-1 text-sm text-zinc-400">Requests from the support page.</p></div>
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-500" />
          <input className="input pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Subject, email or #number" />
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {TABS.map(([value, label]) => (
          <button key={value} onClick={() => setStatus(value)}
            className={`rounded-full border px-3 py-1 text-xs transition ${status === value ? "border-aqua/50 bg-aqua/10 text-white" : "border-white/10 text-zinc-400 hover:text-white"}`}>
            {label}{value && data ? ` · ${data.counts[value] ?? 0}` : ""}</button>
        ))}
      </div>
      {!data ? <Spinner /> : (
        <Card className="overflow-hidden !p-0">
          <ul className="divide-y divide-white/5">
            {data.tickets.map((t) => (
              <li key={t.id}>
                <Link to={`/admin/support/${t.id}`} className="flex items-start gap-3 px-4 py-3 hover:bg-white/[0.03]">
                  <span className="mt-0.5 font-mono text-xs text-zinc-500">#{t.number}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-zinc-100">{t.subject}</p>
                    <p className="truncate text-xs text-zinc-500">{t.name || t.email} · {SUPPORT_CATEGORIES[t.category] ?? t.category}{t.last_from === "user" && t.message_count > 1 ? " · new reply" : ""}</p>
                    <p className="truncate text-xs text-zinc-600">{t.preview}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <span className={`rounded-full px-2 py-0.5 text-[11px] capitalize ${TONE[t.status]}`}>{t.status}</span>
                    <p className="mt-1 text-xs text-zinc-500">{timeAgo(t.updated_at)}</p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          {!data.tickets.length && <p className="p-6 text-sm text-zinc-500">No requests{status ? ` marked ${status}` : ""}.</p>}
        </Card>
      )}
      <SupportSettings />
    </div>
  );
}

export function SupportTicketPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const [t, setT] = useState<(AdminTicket & { user: null | { id: string; display_name: string; email: string | null; is_disabled: boolean }; email_ready: boolean }) | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api(`/admin/support/${id}`).then(setT).catch((e) => { toast(errorText(e), "error"); nav("/admin/support"); }), [id, nav, toast]);
  useEffect(() => { load(); }, [load]);
  if (!t) return <Spinner />;
  const send = async (status: "waiting" | "closed") => {
    setBusy(status);
    try {
      const r = await api<{ emailed: boolean }>(`/admin/support/${t.id}/reply`, { body: { message: reply, status } });
      toast(r.emailed ? "Reply sent and emailed" : t.user_id ? "Reply saved. They'll see it on the support page." : "Reply saved, but email isn't set up: use “Email them” too.");
      setReply(""); load();
    } catch (e) { toast(errorText(e), "error"); } finally { setBusy(""); }
  };
  const setStatus = async (status: string) => {
    try { await api(`/admin/support/${t.id}`, { method: "PATCH", body: { status } }); load(); } catch (e) { toast(errorText(e), "error"); }
  };
  const mailto = `mailto:${t.email}?subject=${encodeURIComponent(`Re: ${t.subject} [#${t.number}]`)}&body=${encodeURIComponent(reply)}`;
  return (
    <div className="space-y-6">
      <Link to="/admin/support" className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white"><ArrowLeft className="size-4" /> All requests</Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs text-zinc-500">#{t.number} · {SUPPORT_CATEGORIES[t.category] ?? t.category}</p>
          <h2 className="text-2xl font-semibold text-white">{t.subject}</h2>
          <p className="mt-1 text-sm text-zinc-400">{t.name && `${t.name} · `}<a href={`mailto:${t.email}`} className="text-aqua hover:underline">{t.email}</a>
            {t.user ? <> · <Link to={`/admin/users/${t.user.id}`} className="text-aqua hover:underline">account</Link>{t.user.is_disabled && " (disabled)"}</> : t.user_id ? " · account deleted" : " · not signed in"}</p>
        </div>
        <select className="input !w-auto" value={t.status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Open</option><option value="waiting">Waiting on them</option><option value="closed">Closed</option>
        </select>
      </div>
      <Card><Thread ticket={t} /></Card>
      <Card title="Reply">
        <textarea className="input min-h-32" value={reply} maxLength={5000} onChange={(e) => setReply(e.target.value)}
          placeholder={t.user_id ? "They'll see this on their support page" : "They sent this signed out, so replies reach them by email only"} />
        {!t.email_ready && <div className="mt-3"><Notice tone="warn">Email isn't set up, so replies aren't emailed.{t.user_id ? " They'll see it when they visit the support page." : " Use “Email them” to reply from your own mail app."}</Notice></div>}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" loading={busy === "waiting"} disabled={!reply.trim()} onClick={() => send("waiting")}><Send className="size-4" /> Reply</Button>
          <Button loading={busy === "closed"} disabled={!reply.trim()} onClick={() => send("closed")}>Reply & close</Button>
          <a href={mailto} className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm text-zinc-300 hover:bg-white/5 hover:text-white"><Mail className="size-4" /> Email them</a>
        </div>
      </Card>
      <Card title="Details">
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[8rem_1fr]">
          <dt className="text-zinc-500">Received</dt><dd className="text-zinc-300">{formatDateTime(t.created_at)}</dd>
          {t.context.page && <><dt className="text-zinc-500">From page</dt><dd className="font-mono text-xs text-zinc-300">{t.context.page}</dd></>}
          {t.context.ip && <><dt className="text-zinc-500">IP</dt><dd className="font-mono text-xs text-zinc-300">{t.context.ip}</dd></>}
          {t.context.user_agent && <><dt className="text-zinc-500">Browser</dt><dd className="break-all text-xs text-zinc-400">{t.context.user_agent}</dd></>}
        </dl>
      </Card>
    </div>
  );
}
