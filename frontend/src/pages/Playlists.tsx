import { ExternalLink, ListMusic, Lock, Pencil, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Generation, type GenerationSummary } from "../api";
import { errorText, formatDate, linkButton, Notice, Spinner, useToast } from "../ui";
import { useSession } from "../session";
import { PlaylistList } from "./SpotifyPlaylists";

function OnSpotify() {
  const { me, config } = useSession();
  const nav = useNavigate();
  const toast = useToast();
  const [loading, setLoading] = useState("");
  const open = async (id: string) => {
    setLoading(id);
    try { nav(`/playlists/${(await api<Generation>("/generations/import", { body: { playlist_id: id } })).id}`); }
    catch (e) { toast(errorText(e), "error"); setLoading(""); }
  };
  if (me && !me.membership.features.edit_playlists) return (
    <div className="card grid place-items-center gap-3 py-16 text-center">
      <Lock className="size-8 text-zinc-600" />
      <p className="text-zinc-300">Editing your Spotify playlists isn't included in your plan.</p>
      {config?.billing_enabled && <Link to="/pricing" className={linkButton("primary")}>See plans</Link>}
    </div>
  );
  return (
    <div className="card p-3 sm:p-4">
      <p className="mb-3 px-2 text-sm text-zinc-400">Pick one of your playlists to refine it with AI. Saving replaces its songs on Spotify. Only playlists you own are shown.</p>
      <PlaylistList onPick={(p) => open(p.id)}
        disabled={(p) => (p.total > 100 ? "Over 100 songs: use it as inspiration instead" : p.total ? (loading && loading !== p.id ? "Opening another playlist…" : null) : "Empty playlist")}
        action={(p) => <span className="flex items-center gap-1.5 rounded-lg bg-ink-700 px-3 py-1.5 text-xs text-zinc-100">
          {loading === p.id ? "Loading…" : <><Pencil className="size-3.5" /> Edit</>}</span>} />
    </div>
  );
}

export default function Playlists() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "spotify" ? "spotify" : "made";
  const [items, setItems] = useState<GenerationSummary[] | null>(null);
  const [error, setError] = useState("");
  const toast = useToast();
  useEffect(() => { api<GenerationSummary[]>("/generations").then(setItems).catch((e) => setError(errorText(e))); }, []);
  const remove = async (g: GenerationSummary) => {
    const where = g.imported ? "It stays on Spotify; this only drops your edits here." : g.spotify_playlist_url ? "It stays on Spotify if you saved it." : "";
    if (!confirm(`Remove “${g.title}” from this list? ${where}`)) return;
    try { await api(`/generations/${g.id}`, { method: "DELETE" }); setItems((xs) => xs?.filter((x) => x.id !== g.id) ?? null); toast("Removed"); }
    catch (e) { toast(errorText(e), "error"); }
  };
  const tabBtn = (t: string, label: string) => (
    <button onClick={() => setParams(t === "made" ? {} : { tab: t })}
      className={`rounded-lg px-4 py-2 text-sm transition ${tab === t ? "bg-ink-700 text-white shadow" : "text-zinc-400 hover:text-white"}`}>{label}</button>
  );
  return (
    <div>
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">My playlists</h1>
          <p className="mt-1 text-zinc-400">Everything you've made or edited here, and your Spotify playlists to edit.</p>
        </div>
        <Link to="/create" className={linkButton("primary")}><Plus className="size-4" /> New</Link>
      </div>
      <div className="mb-6 inline-flex gap-1 rounded-xl bg-ink-850 p-1">{tabBtn("made", "Made here")}{tabBtn("spotify", "Your Spotify playlists")}</div>
      {tab === "spotify" ? <OnSpotify /> : error ? <Notice tone="error">{error}</Notice> : !items ? <Spinner /> : !items.length ? (
        <div className="card grid place-items-center gap-3 py-20 text-center">
          <ListMusic className="size-10 text-zinc-600" />
          <p className="text-zinc-400">No playlists yet.</p>
          <Link to="/create" className="text-aqua hover:underline">Make your first one →</Link>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((g) => (
            <Link key={g.id} to={`/playlists/${g.id}`} className="card group relative overflow-hidden p-3 transition hover:border-white/15 hover:bg-ink-850">
              <button onClick={(e) => { e.preventDefault(); remove(g); }} title="Remove from this list" aria-label="Remove from this list"
                className="absolute right-5 top-5 z-10 rounded-full bg-black/60 p-1.5 text-zinc-300 backdrop-blur transition hover:bg-red-500/80 hover:text-white [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100">
                <X className="size-3.5" /></button>
              {g.imported && <span className="absolute left-5 top-5 z-10 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-medium uppercase text-zinc-200 backdrop-blur">From Spotify</span>}
              <div className="aspect-square overflow-hidden rounded-xl bg-ink-800">
                {g.cover ? <img src={g.cover} alt="" loading="lazy" className="size-full object-cover transition duration-500 group-hover:scale-105" />
                  : <div className="grid size-full place-items-center"><ListMusic className="size-8 text-zinc-600" /></div>}
              </div>
              <h3 className="mt-3 truncate font-medium text-white">{g.title}</h3>
              <p className="flex items-center gap-1.5 text-xs text-zinc-500">
                {g.matched} songs · {formatDate(g.updated_at)}
                {g.spotify_playlist_url && <ExternalLink className="ml-auto size-3.5 text-mint" aria-label="Saved to Spotify" />}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
