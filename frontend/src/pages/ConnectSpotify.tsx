import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { spotifyStartUrl } from "../api";
import { useSession } from "../session";
import { Card, linkButton, Notice } from "../ui";
import { SpotifyIcon } from "./SignInOptions";

const CLIENT_ID_RE = /^[0-9a-f]{32}$/;
const STORE_KEY = "vibeify.spotifyClientId";
const OLD_STORE_KEY = "smartlists.spotifyClientId";   // before the rename

function storedClientId() { try { return localStorage.getItem(STORE_KEY) ?? localStorage.getItem(OLD_STORE_KEY) ?? ""; } catch { return ""; } }

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-ink-850 p-1.5 pl-3.5">
      <code className="min-w-0 flex-1 truncate text-sm text-mint">{value}</code>
      <button type="button" onClick={async () => { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
        className="inline-flex items-center gap-1.5 rounded-lg bg-ink-700 px-3 py-1.5 text-xs text-zinc-100 hover:bg-ink-600">
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="relative flex gap-4 pb-8 last:pb-0">
      <span className="grid size-8 shrink-0 place-items-center rounded-full border border-aqua/40 bg-aqua/10 text-sm font-semibold text-aqua">{n}</span>
      <div className="min-w-0 flex-1 pt-1">
        <h3 className="font-medium text-white">{title}</h3>
        <div className="mt-2 space-y-3 text-sm text-zinc-400">{children}</div>
      </div>
    </li>
  );
}

export default function ConnectSpotify() {
  const { config, me } = useSession();
  const [params] = useSearchParams();
  const [clientId, setClientId] = useState(storedClientId);
  if (!config) return null;
  const error = params.get("error");
  const rawNext = params.get("next");
  const next = rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";   // e.g. back to /pricing
  const app = params.get("app");
  const mode = me ? "link" : "login";
  const trimmed = clientId.trim().toLowerCase();
  const valid = CLIENT_ID_RE.test(trimmed);
  const remember = () => { try { localStorage.setItem(STORE_KEY, trimmed); } catch { /* private mode */ } };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Connect Spotify</h1>
        <p className="mt-2 text-zinc-400">
          {config.site_name} creates playlists in your Spotify account. {me?.spotify
            ? <>You're connected as <b className="text-white">{me.spotify.display_name || me.spotify.spotify_user_id}</b>. You can reconnect below.</>
            : "Connect once and you're set."}
        </p>
      </div>

      {error === "not_registered" && app === "site" && (
        <Notice tone="warn">
          <b>Spotify only lets this site's app serve a few approved accounts</b>, and yours isn't one of them yet.
          You can still use {config.site_name} with your own free Spotify developer app below. It takes about two minutes.
        </Notice>
      )}
      {error === "not_registered" && app === "own" && (
        <Notice tone="warn">
          Spotify refused the connection. Check you signed in to Spotify with the <b>same account that owns the app</b>.
          Spotify also requires the app owner to have <b>Spotify Premium</b> for apps in Development Mode. To use the app with
          another account, add it under <i>User Management</i> in the app's settings.
        </Notice>
      )}
      {error === "redirect" && (
        <Notice tone="error">Spotify says the redirect URI doesn't match. Check step 2: the URI must match exactly, with no trailing slash.</Notice>
      )}
      {error === "spotify" && <Notice tone="error">Spotify sign-in didn't work. Check the Client ID and try again.</Notice>}

      {config.sign_in.spotify_site_app && error !== "not_registered" && (
        <Card>
          <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-semibold text-white">Quick connect</h2>
              <p className="text-sm text-zinc-400">Use {config.site_name}'s Spotify app. Nothing to set up.</p>
            </div>
            <a href={spotifyStartUrl({ mode, returnTo: next })} className={linkButton("spotify", "shrink-0")}>
              <SpotifyIcon /> Continue with Spotify
            </a>
          </div>
        </Card>
      )}

      {config.sign_in.spotify_own_app && (
        <Card title="Use your own Spotify app">
          <p className="mb-6 text-sm text-zinc-400">
            Spotify limits how many people one app can serve, so you can connect through your own free developer app instead.
            Your app's details stay in your browser and your account. {config.site_name} only needs the Client ID, never a secret.
          </p>
          <ol>
            <Step n={1} title="Create a Spotify app">
              <p>Sign in to the Spotify Developer Dashboard and click <b className="text-zinc-200">Create app</b>.
                Any name and description will do, e.g. &ldquo;My {config.site_name}&rdquo;.</p>
              <a href="https://developer.spotify.com/dashboard/create" target="_blank" rel="noreferrer" className={linkButton("secondary", "text-xs")}>
                Open Spotify Developer Dashboard <ExternalLink className="size-3.5" />
              </a>
            </Step>
            <Step n={2} title="Add this redirect URI">
              <p>Paste this into <b className="text-zinc-200">Redirect URIs</b>, click <b className="text-zinc-200">Add</b>, tick <b className="text-zinc-200">Web API</b>, accept the terms, and save.</p>
              <CopyField value={config.spotify_redirect_uri} />
            </Step>
            <Step n={3} title="Paste your Client ID">
              <p>Open your new app's <b className="text-zinc-200">Settings</b> and copy the <b className="text-zinc-200">Client ID</b>. You don't need the secret.</p>
              <input className="input font-mono" placeholder="e.g. 1a2b3c4d5e6f…" value={clientId} spellCheck={false}
                onChange={(e) => setClientId(e.target.value)} />
              {clientId && !valid && <p className="text-xs text-amber-300">A Client ID is 32 letters (a–f) and numbers.</p>}
            </Step>
            <Step n={4} title="Connect">
              <a href={valid ? spotifyStartUrl({ mode, clientId: trimmed, returnTo: next }) : undefined} onClick={remember}
                aria-disabled={!valid} className={linkButton("spotify", valid ? "" : "pointer-events-none opacity-40")}>
                <SpotifyIcon /> Connect with my app
              </a>
            </Step>
          </ol>
        </Card>
      )}
      {!me && <p className="text-center text-sm text-zinc-500">Prefer another way? <Link to="/signin" className="text-aqua">See all sign-in options</Link></p>}
    </div>
  );
}
