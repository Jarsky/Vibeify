import { CheckCircle2, MailCheck } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useSession } from "../session";
import { Button, errorText, Field, Notice } from "../ui";
import SignInOptions, { SIGNIN_ERRORS } from "./SignInOptions";

function AuthCard({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-md py-6">
      <div className="card p-6 sm:p-8">
        <h1 className="text-2xl font-semibold text-white">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm text-zinc-400">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </div>
    </div>
  );
}

export function SignIn() {
  const [params] = useSearchParams();
  const { config, me } = useSession();
  const error = params.get("error");
  const next = params.get("next") || undefined;
  if (me) return <AuthCard title="You're signed in"><Link className="text-aqua" to="/">Go to your home page →</Link></AuthCard>;
  return (
    <AuthCard title={`Sign in to ${config?.site_name ?? ""}`} subtitle="New here? Signing in creates your account.">
      {error && <div className="mb-4"><Notice tone="error">{SIGNIN_ERRORS[error] ?? "Sign-in didn't work. Please try again."}</Notice></div>}
      <SignInOptions next={next} />
    </AuthCard>
  );
}

export function SignUp() {
  const { config } = useSession();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!config?.sign_in.email) return <AuthCard title="Email sign-up is off">Use one of the <Link to="/signin" className="text-aqua">other sign-in options</Link>.</AuthCard>;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try { await api("/auth/email/start", { body: { email } }); setSent(true); }
    catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  };
  if (sent) return (
    <AuthCard title="Check your inbox">
      <div className="flex gap-3 text-sm text-zinc-300"><MailCheck className="size-6 shrink-0 text-mint" />
        <p>We sent a link to <b className="text-white">{email}</b>. Open it to confirm your address and choose a password. It works for 24 hours.</p></div>
    </AuthCard>
  );
  return (
    <AuthCard title="Create an account" subtitle="We'll email you a link to confirm your address, then you choose a password.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email"><input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button variant="primary" className="w-full" loading={busy}>Send confirmation link</Button>
        <p className="text-center text-sm text-zinc-400">Already have an account? <Link className="text-aqua" to="/signin">Sign in</Link></p>
      </form>
    </AuthCard>
  );
}

function PasswordForm({ endpoint, title, subtitle, askName }: { endpoint: string; title: string; subtitle: string; askName?: boolean }) {
  const [params] = useSearchParams();
  const { refresh } = useSession();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const token = params.get("token") ?? "";
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (password !== confirm) return setError("The passwords don't match.");
    setBusy(true);
    try {
      await api(endpoint, { body: { token, password, display_name: name } });
      await refresh();
      nav("/connect-spotify");
    } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  };
  if (!token) return <AuthCard title={title}><Notice tone="error">This link is incomplete. Open it straight from the email.</Notice></AuthCard>;
  return (
    <AuthCard title={title} subtitle={subtitle}>
      <form onSubmit={submit} className="space-y-4">
        {askName && <Field label="Your name"><input className="input" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Shown on your account" /></Field>}
        <Field label="Password" hint="At least 10 characters. A few random words works well.">
          <input className="input" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Confirm password"><input className="input" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
        {error && <Notice tone="error">{error}</Notice>}
        <Button variant="primary" className="w-full" loading={busy}><CheckCircle2 className="size-4" /> Continue</Button>
      </form>
    </AuthCard>
  );
}

export const VerifyEmail = () => <PasswordForm endpoint="/auth/email/complete" title="Choose a password" subtitle="Your email is confirmed once you set a password." askName />;
export const ResetPassword = () => <PasswordForm endpoint="/auth/password/reset" title="Choose a new password" subtitle="You'll be signed in afterwards." />;

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try { await api("/auth/password/forgot", { body: { email } }); setSent(true); }
    catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  };
  return (
    <AuthCard title="Reset your password" subtitle="We'll email you a link to choose a new one.">
      {sent ? <Notice tone="success">If an account uses {email}, a reset link is on its way. It works for 2 hours.</Notice> : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Email"><input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          {error && <Notice tone="error">{error}</Notice>}
          <Button variant="primary" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
    </AuthCard>
  );
}
