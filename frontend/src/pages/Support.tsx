import { CheckCircle2, ChevronDown, LifeBuoy, MessageCircle, Send } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, SUPPORT_CATEGORIES, type SupportTicket } from "../api";
import { useSession } from "../session";
import { Button, Card, errorText, Field, formatDateTime, Notice, timeAgo, useToast } from "../ui";

function faqs(site: string, billing: boolean): { q: string; a: ReactNode }[] {
  return [
    { q: "Why does Spotify say I'm not registered, or refuse to connect?", a: <>
      Spotify only lets a new app serve a handful of people until Spotify approves it for more. If the one-click option doesn't work for you,
      use <Link to="/connect-spotify" className="text-aqua hover:underline">your own free Spotify developer app</Link> instead. It takes about two minutes.
      Spotify requires the owner of a developer app to have Spotify Premium.</> },
    { q: "Some suggested songs say “not found on Spotify”.", a: <>
      The AI suggests songs by name, and {site} then looks each one up on Spotify. Songs that aren't on Spotify in your country, or that the AI
      got slightly wrong, are skipped and never saved. Ask it to “replace the missing songs” in the chat to fill the gaps.</> },
    { q: "Will editing a playlist change it on Spotify?", a: <>
      Only when you press <b>Update on Spotify</b>. That replaces the playlist's songs on Spotify with the list you see here. Until then nothing changes.</> },
    { q: "Which AI makes my playlists?", a: <>The model in use is shown under the create form (“Powered by …”). If the site lets you, you can choose another one or add your own key on your Account page.</> },
    { q: "Is my shared playlist public?", a: <>
      “Share anonymously” shows the title, description, cover art and main artists to other people signed in here. It isn't shown on the public front page.
      Your name is never shown. You can un-share it any time from the playlist.</> },
    ...(billing ? [{ q: "How do I change or cancel my plan?", a: <>Go to <Link to="/account" className="text-aqua hover:underline">Account</Link> → Manage billing.
      Cancelling keeps your plan until the end of the period you've paid for. Deleting your account cancels it immediately.</> }] : []),
    { q: "How do I get a copy of my data, or delete my account?", a: <>Both are on your <Link to="/account" className="text-aqua hover:underline">Account</Link> page:
      “Download my data” and “Delete account”. Playlists you saved stay in your Spotify library.</> },
  ];
}

function Faq({ q, a }: { q: string; a: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between gap-4 py-4 text-left text-sm font-medium text-zinc-100 hover:text-white">
        {q}<ChevronDown className={`size-4 shrink-0 text-zinc-500 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <p className="-mt-1 pb-4 text-sm leading-relaxed text-zinc-400">{a}</p>}
    </li>
  );
}

const STATUS: Record<string, { label: string; tone: string }> = {
  open: { label: "Waiting for us", tone: "bg-aqua/10 text-aqua" },
  waiting: { label: "Replied", tone: "bg-mint/15 text-mint" },
  closed: { label: "Closed", tone: "bg-white/5 text-zinc-400" },
};

export function Thread({ ticket }: { ticket: { messages: SupportTicket["messages"] } }) {
  return (
    <ol className="space-y-3">
      {ticket.messages.map((m, i) => (
        <li key={i} className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm ${m.from === "admin" ? "mr-auto rounded-tl-sm border border-aqua/20 bg-aqua/5" : "ml-auto rounded-tr-sm bg-ink-800"}`}>
          <p className="mb-1 text-xs text-zinc-500">{m.author} · {formatDateTime(m.at)}</p>
          <p className="whitespace-pre-wrap break-words text-zinc-100">{m.body}</p>
        </li>
      ))}
    </ol>
  );
}

function MyRequest({ t, open, onToggle, onChange }: { t: SupportTicket; open: boolean; onToggle: () => void; onChange: (t: SupportTicket) => void }) {
  const toast = useToast();
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try { onChange(await api<SupportTicket>(`/support/tickets/${t.id}/reply`, { body: { message: reply } })); setReply(""); toast("Reply sent"); }
    catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); }
  };
  const s = STATUS[t.status];
  return (
    <li className="py-1">
      <button onClick={onToggle} className="flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-white/[0.03]">
        <span className="font-mono text-xs text-zinc-500">#{t.number}</span>
        <span className="min-w-0 flex-1 truncate text-sm text-zinc-100">{t.subject}</span>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${s.tone}`}>{s.label}</span>
        <span className="hidden shrink-0 text-xs text-zinc-500 sm:block">{timeAgo(t.updated_at)}</span>
      </button>
      {open && (
        <div className="space-y-4 px-2 pb-4 pt-2">
          <Thread ticket={t} />
          <div className="flex gap-2">
            <textarea className="input min-h-[2.75rem]" rows={2} value={reply} maxLength={5000} onChange={(e) => setReply(e.target.value)}
              placeholder={t.status === "closed" ? "Reply to reopen this request…" : "Add a reply…"} />
            <Button variant="primary" className="self-end px-3" loading={busy} disabled={!reply.trim()} onClick={send} aria-label="Send">{!busy && <Send className="size-4" />}</Button>
          </div>
          {t.status !== "closed" && <button className="text-xs text-zinc-500 hover:text-white" onClick={async () => {
            try { onChange(await api<SupportTicket>(`/support/tickets/${t.id}/close`, { body: {} })); } catch (e) { toast(errorText(e), "error"); }
          }}>Mark as solved</button>}
        </div>
      )}
    </li>
  );
}

function MyRequests({ refreshKey }: { refreshKey: number }) {
  const [params] = useSearchParams();
  const [items, setItems] = useState<SupportTicket[] | null>(null);
  const [open, setOpen] = useState<string | null>(params.get("ticket"));
  useEffect(() => { api<SupportTicket[]>("/support/tickets").then(setItems).catch(() => setItems([])); }, [refreshKey]);
  if (!items?.length) return null;
  return (
    <Card title="Your requests">
      <ul className="-mx-2 divide-y divide-white/5">
        {items.map((t) => <MyRequest key={t.id} t={t} open={open === t.id} onToggle={() => setOpen(open === t.id ? null : t.id)}
          onChange={(n) => setItems(items.map((x) => (x.id === n.id ? n : x)))} />)}
      </ul>
    </Card>
  );
}

function ContactForm({ onSent }: { onSent: () => void }) {
  const { me } = useSession();
  const [category, setCategory] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState<number | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const r = await api<{ number: number }>("/support", { body: { category, subject, message, name, email, website, page: document.referrer ? new URL(document.referrer).pathname : "" } });
      setSent(r.number); onSent();
    } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  };
  if (sent !== null) return (
    <Card>
      <div className="grid place-items-center gap-3 py-8 text-center">
        <CheckCircle2 className="size-10 text-mint" />
        <h2 className="text-xl font-semibold text-white">Thanks, we got it{sent ? ` (#${sent})` : ""}</h2>
        <p className="max-w-md text-sm text-zinc-400">{me ? "You'll see our reply under “Your requests” on this page, and by email if it's set up." : "We'll reply to the email address you gave."}</p>
        <Button onClick={() => { setSent(null); setSubject(""); setMessage(""); setCategory(""); }}>Send another</Button>
      </div>
    </Card>
  );
  return (
    <Card title="Contact us">
      <form className="space-y-5" onSubmit={submit}>
        <div>
          <span className="label">What's it about?</span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(SUPPORT_CATEGORIES).map(([k, label]) => (
              <button type="button" key={k} onClick={() => setCategory(k)}
                className={`rounded-full border px-3 py-1.5 text-sm transition ${category === k ? "border-aqua/60 bg-aqua/10 text-white" : "border-white/10 text-zinc-400 hover:text-white"}`}>{label}</button>
            ))}
          </div>
        </div>
        {!me && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Your name"><input className="input" value={name} maxLength={120} autoComplete="name" onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Email" hint="So we can reply."><input className="input" type="email" required value={email} autoComplete="email" onChange={(e) => setEmail(e.target.value)} /></Field>
          </div>
        )}
        <Field label="Subject"><input className="input" required minLength={3} maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)}
          placeholder={category === "bug" ? "e.g. Saving to Spotify fails" : "A short summary"} /></Field>
        <Field label="Message" hint={category === "bug" ? "What did you do, what happened, and what did you expect? Error messages help a lot." : undefined}>
          <textarea className="input min-h-36" required minLength={10} maxLength={5000} value={message} onChange={(e) => setMessage(e.target.value)} /></Field>
        <input type="text" tabIndex={-1} autoComplete="off" aria-hidden="true" className="hidden" value={website} onChange={(e) => setWebsite(e.target.value)} name="website" />
        {me && <p className="text-xs text-zinc-500">Sending as {me.display_name}{me.email ? ` (${me.email})` : ""}.</p>}
        {error && <Notice tone="error">{error}</Notice>}
        <Button variant="primary" loading={busy} disabled={!category || subject.trim().length < 3 || message.trim().length < 10 || (!me && !email)}>
          <MessageCircle className="size-4" /> Send
        </Button>
      </form>
    </Card>
  );
}

export default function Support() {
  const { me, config } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const site = config?.site_name ?? "this site";
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="flex items-center gap-3 text-3xl font-bold tracking-tight text-white"><LifeBuoy className="size-7 text-aqua" /> Support</h1>
        <p className="mt-1 text-zinc-400">Answers to common questions, and a way to reach us about anything else.</p>
      </div>
      {me && <MyRequests refreshKey={refreshKey} />}
      <Card title="Common questions">
        <ul className="-my-2 divide-y divide-white/5">{faqs(site, !!config?.billing_enabled).map((f) => <Faq key={f.q} {...f} />)}</ul>
      </Card>
      {config?.support_enabled === false ? <Notice tone="info">The contact form is turned off right now.</Notice> : <ContactForm onSent={() => setRefreshKey((k) => k + 1)} />}
    </div>
  );
}
