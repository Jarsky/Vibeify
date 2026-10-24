import { useState } from "react";
import { api } from "../../api";
import { useSession } from "../../session";
import { Button, Card, errorText, Field, Notice, Spinner, Toggle, useToast } from "../../ui";
import { SecretInput, useSettings } from "./common";

function Header({ title, text }: { title: string; text: string }) {
  return <div><h2 className="text-2xl font-semibold text-white">{title}</h2><p className="mt-1 text-sm text-zinc-400">{text}</p></div>;
}

export function SignInSettings() {
  const { settings, setSettings, save, saving } = useSettings();
  const { config } = useSession();
  const [googleSecret, setGoogleSecret] = useState("");
  const [spotifySecret, setSpotifySecret] = useState("");
  if (!settings || !config) return <Spinner />;
  const set = (k: string) => (v: any) => setSettings({ ...settings, [k]: v });
  const googleRedirect = config.spotify_redirect_uri.replace("/spotify/callback", "/google/callback");
  const submit = () => save({
    signup_open: settings.signup_open, auth_spotify_site_app: settings.auth_spotify_site_app, auth_spotify_byo: settings.auth_spotify_byo,
    auth_google: settings.auth_google, auth_email: settings.auth_email, spotify_client_id: settings.spotify_client_id,
    google_client_id: settings.google_client_id, ...(googleSecret ? { google_client_secret: googleSecret } : {}),
    ...(spotifySecret ? { spotify_client_secret: spotifySecret } : {}),
  }).then((ok) => { if (ok) { setGoogleSecret(""); setSpotifySecret(""); } });

  return (
    <div className="space-y-6">
      <Header title="Sign-in & Spotify" text="Choose how people create accounts and connect Spotify." />
      <Card title="Accounts">
        <Toggle checked={settings.signup_open} onChange={set("signup_open")} label="Allow new sign-ups" hint="When off, only existing accounts can sign in." />
      </Card>
      <Card title="Spotify">
        <div className="space-y-5">
          <Toggle checked={settings.auth_spotify_site_app} onChange={set("auth_spotify_site_app")} label="“Continue with Spotify” using the site's app"
            hint="One click for users. In Spotify's Development Mode an app only works for 5 accounts you add under User Management, and the owner needs Premium. Apps with extended quota have no limit." />
          <Field label="Site Spotify Client ID" hint={<>From your app at developer.spotify.com. Add this redirect URI to the app: <code className="text-mint">{config.spotify_redirect_uri}</code></>}>
            <input className="input font-mono" value={settings.spotify_client_id} onChange={(e) => set("spotify_client_id")(e.target.value.trim())} placeholder="32 characters" />
          </Field>
          <Field label="Site Spotify Client secret" hint="Optional. Lets the public landing page show new releases and popular playlists without anyone signed in (Settings → View client secret on your Spotify app). Sign-in doesn't use it.">
            <SecretInput isSet={settings.spotify_client_secret} value={spotifySecret} onChange={setSpotifySecret} />
          </Field>
          <Toggle checked={settings.auth_spotify_byo} onChange={set("auth_spotify_byo")} label="Let users connect their own Spotify app"
            hint="A guided setup where users create a free Spotify app and paste its Client ID. This is how the site scales past Spotify's per-app user limit." />
        </div>
      </Card>
      <Card title="Google">
        <div className="space-y-5">
          <Toggle checked={settings.auth_google} onChange={set("auth_google")} label="Sign in with Google" />
          <p className="text-sm text-zinc-400">Create an OAuth client (type <i>Web application</i>) in Google Cloud Console → APIs & Services → Credentials.
            Authorised redirect URI: <code className="text-mint">{googleRedirect}</code></p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Client ID"><input className="input font-mono" value={settings.google_client_id} onChange={(e) => set("google_client_id")(e.target.value.trim())} /></Field>
            <Field label="Client secret"><SecretInput isSet={settings.google_client_secret} value={googleSecret} onChange={setGoogleSecret} /></Field>
          </div>
        </div>
      </Card>
      <Card title="Email">
        <Toggle checked={settings.auth_email} onChange={set("auth_email")} label="Email sign-up with a confirmation link"
          hint="Needs working SMTP settings on the Email page." />
      </Card>
      <Button variant="primary" loading={saving} onClick={submit}>Save changes</Button>
    </div>
  );
}

export function EmailSettings() {
  const { settings, setSettings, save, saving } = useSettings();
  const { me } = useSession();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [testTo, setTestTo] = useState(me?.email ?? "");
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState("");
  if (!settings) return <Spinner />;
  const set = (k: string) => (v: any) => setSettings({ ...settings, [k]: v });
  const submit = () => save({
    smtp_host: settings.smtp_host, smtp_port: settings.smtp_port, smtp_username: settings.smtp_username,
    smtp_from: settings.smtp_from, smtp_security: settings.smtp_security, ...(password ? { smtp_password: password } : {}),
  }).then((ok) => ok && setPassword(""));
  const test = async () => {
    setTesting(true); setTestError("");
    try { await api("/admin/settings/test-email", { body: { to: testTo } }); toast(`Test email sent to ${testTo}`); }
    catch (e) { setTestError(errorText(e)); } finally { setTesting(false); }
  };
  return (
    <div className="space-y-6">
      <Header title="Email" text="Used for sign-up confirmation and password reset links." />
      <Card title="SMTP server">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Host"><input className="input" value={settings.smtp_host} onChange={(e) => set("smtp_host")(e.target.value)} placeholder="smtp.example.com" /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Port"><input className="input" inputMode="numeric" value={settings.smtp_port} onChange={(e) => set("smtp_port")(e.target.value.replace(/\D/g, ""))} /></Field>
            <Field label="Security">
              <select className="input" value={settings.smtp_security} onChange={(e) => set("smtp_security")(e.target.value)}>
                <option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option><option value="none">None</option>
              </select>
            </Field>
          </div>
          <Field label="Username"><input className="input" autoComplete="off" value={settings.smtp_username} onChange={(e) => set("smtp_username")(e.target.value)} /></Field>
          <Field label="Password"><SecretInput isSet={settings.smtp_password} value={password} onChange={setPassword} /></Field>
          <div className="sm:col-span-2"><Field label="From address" hint='e.g. "Vibeify <noreply@vibeify.nz>"'>
            <input className="input" value={settings.smtp_from} onChange={(e) => set("smtp_from")(e.target.value)} /></Field></div>
        </div>
        <Button variant="primary" className="mt-6" loading={saving} onClick={submit}>Save</Button>
      </Card>
      <Card title="Send a test email">
        <div className="flex gap-3">
          <input className="input" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="you@example.com" />
          <Button loading={testing} disabled={!testTo} onClick={test}>Send</Button>
        </div>
        {testError && <div className="mt-3"><Notice tone="error">{testError}</Notice></div>}
      </Card>
    </div>
  );
}

export function SiteSettings() {
  const { settings, setSettings, save, saving } = useSettings();
  if (!settings) return <Spinner />;
  const set = (k: string) => (v: any) => setSettings({ ...settings, [k]: v });
  const num = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => set(k)(e.target.value.replace(/\D/g, ""));
  return (
    <div className="space-y-6">
      <Header title="Site & limits" text="Branding, and how much of the site's AI allowance each user gets." />
      <Card title="Branding">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Site name"><input className="input" value={settings.site_name} maxLength={60} onChange={(e) => set("site_name")(e.target.value)} /></Field>
          <Field label="Tagline" hint="Two short sentences work best on the home page."><input className="input" value={settings.site_tagline} maxLength={120} onChange={(e) => set("site_tagline")(e.target.value)} /></Field>
        </div>
      </Card>
      <Card title="Default limits">
        <div className="grid gap-4 sm:grid-cols-4">
          <Field label="AI requests per day" hint="0 = unlimited"><input className="input" inputMode="numeric" value={settings.default_daily_generations} onChange={num("default_daily_generations")} /></Field>
          <Field label="AI tokens per day" hint="0 = unlimited"><input className="input" inputMode="numeric" value={settings.default_daily_tokens} onChange={num("default_daily_tokens")} /></Field>
          <Field label="AI tokens per month" hint="0 = unlimited"><input className="input" inputMode="numeric" value={settings.default_monthly_tokens} onChange={num("default_monthly_tokens")} /></Field>
          <Field label="Max songs per playlist"><input className="input" inputMode="numeric" value={settings.max_playlist_size} onChange={num("max_playlist_size")} /></Field>
        </div>
        <p className="mt-3 text-xs text-zinc-500">Used when there are no plans, or a plan leaves a limit blank. Plans are under Plans & billing; per-user overrides on the Users page win over both.</p>
        <div className="mt-5"><Toggle checked={settings.allow_user_llm_keys} onChange={set("allow_user_llm_keys")} label="Let users add their own AI keys"
          hint="Off: everyone uses the site's models and the limits above. On: users may add their own key, which isn't limited." /></div>
        <div className="mt-5"><Toggle checked={settings.allow_model_choice} onChange={set("allow_model_choice")} label="Let users choose the AI model"
          hint="Off: everyone gets the default model (set on the Models page) and sees its name on the create page. On: users pick from every enabled model their plan allows." /></div>
      </Card>
      <Card title="Records">
        <div className="max-w-xs"><Field label="Keep the audit log for (days)" hint="0 = forever. Older entries are removed when the app starts and when you open the log.">
          <input className="input" inputMode="numeric" value={settings.audit_retention_days} onChange={num("audit_retention_days")} /></Field></div>
      </Card>
      <Button variant="primary" loading={saving} onClick={() => save({
        audit_retention_days: Number(settings.audit_retention_days) || 0,
        site_name: settings.site_name, site_tagline: settings.site_tagline, default_daily_generations: settings.default_daily_generations || 0, default_daily_tokens: settings.default_daily_tokens || 0,
        default_monthly_tokens: settings.default_monthly_tokens || 0, max_playlist_size: Math.min(100, Math.max(5, Number(settings.max_playlist_size) || 50)),
        allow_user_llm_keys: settings.allow_user_llm_keys, allow_model_choice: settings.allow_model_choice,
      })}>Save changes</Button>
    </div>
  );
}
