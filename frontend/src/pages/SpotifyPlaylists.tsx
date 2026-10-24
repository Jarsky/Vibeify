import { Check, ListMusic, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type SpotifyPlaylist } from "../api";
import { errorText, Notice, Spinner } from "../ui";

let cache: Promise<SpotifyPlaylist[]> | null = null;   // one fetch per page load

export function useMyPlaylists() {
  const [items, setItems] = useState<SpotifyPlaylist[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    cache ??= api<SpotifyPlaylist[]>("/spotify/playlists");
    cache.then(setItems).catch((e) => { cache = null; setError(errorText(e)); });
  }, []);
  return { items, error };
}

export function Cover({ src, className = "" }: { src: string | null; className?: string }) {
  return src ? <img src={src} alt="" loading="lazy" className={`object-cover ${className}`} />
    : <span className={`grid place-items-center bg-ink-800 ${className}`}><ListMusic className="size-5 text-zinc-600" /></span>;
}

/** Searchable list of the user's own Spotify playlists; `selected` shows ticks for multi-select. */
export function PlaylistList({ selected, onPick, action, disabled }: {
  selected?: string[]; onPick: (p: SpotifyPlaylist) => void; action?: (p: SpotifyPlaylist) => React.ReactNode; disabled?: (p: SpotifyPlaylist) => string | null;
}) {
  const { items, error } = useMyPlaylists();
  const [q, setQ] = useState("");
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!items) return <Spinner label="Loading your playlists…" />;
  if (!items.length) return <p className="py-6 text-center text-sm text-zinc-500">You don't own any Spotify playlists yet.</p>;
  const shown = items.filter((p) => p.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      {items.length > 8 && (
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-500" />
          <input className="input pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${items.length} playlists`} />
        </div>
      )}
      <ul className="max-h-[28rem] space-y-1 overflow-y-auto pr-1">
        {shown.map((p) => {
          const on = selected?.includes(p.id);
          const why = disabled?.(p) ?? null;
          return (
            <li key={p.id}>
              <button type="button" disabled={!!why} onClick={() => onPick(p)} title={why ?? undefined}
                className={`flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition disabled:cursor-not-allowed disabled:opacity-40
                  ${on ? "bg-mint/10 ring-1 ring-mint/40" : "hover:bg-white/5"}`}>
                <Cover src={p.image} className="size-11 shrink-0 rounded-md" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-zinc-100">{p.name}</span>
                  <span className="block truncate text-xs text-zinc-500">{why ?? `${p.total} songs${p.public ? " · public" : ""}`}</span>
                </span>
                {on && <Check className="size-4 text-mint" />}
                {action?.(p)}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
