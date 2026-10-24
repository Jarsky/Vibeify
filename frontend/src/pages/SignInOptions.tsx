import { KeyRound, Mail } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, googleStartUrl, spotifyStartUrl } from "../api";
import { useSession } from "../session";
import { Button, errorText, linkButton, Notice } from "../ui";

export function SpotifyIcon({ className = "size-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12 0a12 12 0 1 0 0 24 12 12 0 0 0 0-24Zm5.5 17.3a.75.75 0 0 1-1 .25c-2.85-1.74-6.45-2.14-10.68-1.17a.75.75 0 1 1-.33-1.46c4.63-1.06 8.6-.6 11.77 1.34.36.22.47.68.25 1.04Zm1.47-3.27a.94.94 0 0 1-1.29.31c-3.27-2-8.25-2.59-12.11-1.42a.94.94 0 1 1-.55-1.8c4.41-1.33 9.9-.68 13.64 1.62.44.27.58.85.31 1.29Zm.13-3.4C15.18 8.3 8.73 8.08 5 9.21a1.12 1.12 0 1 1-.65-2.15c4.28-1.3 11.4-1.05 15.9 1.62a1.12 1.12 0 0 1-1.15 1.93Z" />
    </svg>
  );
}

export function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden>
      <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.24 1.4-1.7 4.1-5.5 4.1-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.5 14.6 2.5 12 2.5 6.8 2.5 2.6 6.8 2.6 12s4.2 9.5 9.4 9.5c5.4 0 9-3.8 9-9.2 0-.6-.1-1.1-.2-1.6H12Z" />
    </svg>
  );
}

export const SIGNIN_ERRORS: Record<string, string> = {
  expired: "That sign-in took too long or was opened in another browser. Please try again.",
  cancelled: "Sign-in was cancelled.",
  spotify: "Spotify sign-in didn't work. Please try again.",
  google: "Google sign-in didn't work. Please try again.",
  signups_closed: "New sign-ups are closed on this site right now.",
  disabled: "This account has been disabled.",
};

export default function SignInOptions({ next }: { next?: string }) {
  const { config, refresh } = useSession();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!config) return null;
  const s = config.sign_in;
  const nothing = !s.spotify_site_app && !s.spotify_own_app && !s.google && !s.email;

  const login = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await api("/auth/email/login", { body: { email, password } });
      await refresh();
      nav(next || "/");
    } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3">
      {nothing && <Notice tone="warn">Sign-in isn't set up yet. An admin needs to finish setup.</Notice>}
      {s.spotify_site_app && (
        <a href={spotifyStartUrl({ mode: "login", returnTo: next })} className={linkButton("spotify", "w-full py-3")}>
          <SpotifyIcon /> Continue with Spotify
        </a>
      )}
      {s.google && (
        <a href={googleStartUrl(next)} className={linkButton("secondary", "w-full py-3")}><GoogleIcon /> Continue with Google</a>
      )}
      {s.spotify_own_app && (
        <Link to="/connect-spotify" className={linkButton("ghost", "w-full border border-dashed border-white/15")}>
          <KeyRound className="size-4" /> Use my own Spotify app
        </Link>
      )}
      {s.email && (
        <>
          <div className="flex items-center gap-3 py-2 text-xs uppercase tracking-wider text-zinc-500">
            <span className="h-px flex-1 bg-white/10" /> or with email <span className="h-px flex-1 bg-white/10" />
          </div>
          <form onSubmit={login} className="space-y-3">
            <input className="input" type="email" autoComplete="email" placeholder="you@example.com" value={email}
              onChange={(e) => setEmail(e.target.value)} required />
            <input className="input" type="password" autoComplete="current-password" placeholder="Password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
            {error && <Notice tone="error">{error}</Notice>}
            <Button variant="primary" className="w-full" loading={busy}><Mail className="size-4" /> Sign in</Button>
          </form>
          <div className="flex justify-between text-sm">
            <Link to="/forgot-password" className="text-zinc-400 hover:text-white">Forgot password?</Link>
            {config.signup_open && <Link to="/signup" className="text-aqua hover:underline">Create an account</Link>}
          </div>
        </>
      )}
    </div>
  );
}
