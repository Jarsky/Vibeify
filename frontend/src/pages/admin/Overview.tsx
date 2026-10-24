import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useSession } from "../../session";
import { Card, errorText, Notice, Spinner } from "../../ui";

type Stats = {
  days: number; users: number; new_users: number; playlists: number; saved_to_spotify: number;
  by_model: { kind: string; model_id: string; requests: number; input_tokens: number; output_tokens: number; own_key_requests: number }[];
  top_users: { display_name: string; email: string | null; requests: number }[];
  per_day: { date: string; requests: number }[];
};

function Stat({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="card p-5">
      <p className="text-xs uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums text-white">{value.toLocaleString()}</p>
      {sub && <p className="text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

export default function Overview() {
  const { config } = useSession();
  const [stats, setStats] = useState<Stats | null>(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState("");
  useEffect(() => { api<Stats>(`/admin/stats?days=${days}`).then(setStats).catch((e) => setError(errorText(e))); }, [days]);
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!stats || !config) return <Spinner />;
  const s = config.sign_in;
  const setupIssues = [
    !s.spotify_site_app && !s.spotify_own_app && "No Spotify sign-in method is on.",
    !s.spotify_site_app && !s.google && !s.email && s.spotify_own_app && "Only “own Spotify app” sign-in is on; consider Google or email accounts too.",
  ].filter(Boolean) as string[];
  const peak = Math.max(1, ...stats.per_day.map((d) => d.requests));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold text-white">Overview</h2>
        <select className="input w-auto" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>
      {setupIssues.map((i) => <Notice key={i} tone="warn">{i} <Link className="underline" to="/admin/sign-in">Sign-in settings</Link></Notice>)}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Users" value={stats.users} sub={`+${stats.new_users} in ${days} days`} />
        <Stat label="Playlists made" value={stats.playlists} />
        <Stat label="Saved to Spotify" value={stats.saved_to_spotify} />
        <Stat label="AI requests" value={stats.by_model.reduce((a, m) => a + m.requests, 0)} />
      </div>
      <Card title="AI requests per day">
        {stats.per_day.length ? (
          <div className="flex h-32 items-end gap-1">
            {stats.per_day.map((d) => (
              <div key={d.date} title={`${d.date}: ${d.requests}`} className="flex-1 rounded-t bg-aqua/70 hover:bg-aqua" style={{ height: `${(d.requests / peak) * 100}%`, minHeight: 2 }} />
            ))}
          </div>
        ) : <p className="text-sm text-zinc-500">No requests yet.</p>}
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="By model">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-zinc-500"><th className="pb-2 font-medium">Model</th><th className="pb-2 text-right font-medium">Requests</th><th className="pb-2 text-right font-medium">Tokens in / out</th></tr></thead>
            <tbody className="divide-y divide-white/5">
              {stats.by_model.map((m) => (
                <tr key={m.kind + m.model_id}><td className="py-2 text-zinc-200">{m.model_id}<span className="block text-xs text-zinc-500">{config.provider_kinds[m.kind]}{m.own_key_requests ? ` · ${m.own_key_requests} on users' keys` : ""}</span></td>
                  <td className="py-2 text-right tabular-nums">{m.requests}</td>
                  <td className="py-2 text-right tabular-nums text-zinc-400">{m.input_tokens.toLocaleString()} / {m.output_tokens.toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
          {!stats.by_model.length && <p className="text-sm text-zinc-500">Nothing yet.</p>}
        </Card>
        <Card title="Most active users">
          <ul className="divide-y divide-white/5 text-sm">
            {stats.top_users.map((u, i) => (
              <li key={i} className="flex justify-between py-2"><span className="text-zinc-200">{u.display_name}<span className="ml-2 text-xs text-zinc-500">{u.email}</span></span><span className="tabular-nums">{u.requests}</span></li>
            ))}
          </ul>
          {!stats.top_users.length && <p className="text-sm text-zinc-500">Nothing yet.</p>}
        </Card>
      </div>
    </div>
  );
}
