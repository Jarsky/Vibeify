import { ChevronLeft, ChevronRight, Disc3, ExternalLink, Flame, Lightbulb, Music2, Sparkles, Users, Wand2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Album, type CommunityPlaylist, type DiscoverRows, type IdeaPlaylist } from "../api";
import { useSession } from "../session";
import { Button, formatDate, linkButton, Notice, timeAgo } from "../ui";

const QUICK = ["Sunny Sunday drive", "Rainy day lo-fi", "2000s throwbacks", "Gym, no slow songs", "Dinner party jazz"];

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Up late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

const compact = (n: number) => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
const clip = (s: string, n = 300) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function useCreateFrom() {
  const nav = useNavigate();
  return (prompt: string) => nav(`/create?${new URLSearchParams({ prompt: clip(prompt) })}`);
}

// A horizontally scrolling row with arrow buttons on wider screens.
export function Shelf({ icon: Icon, title, subtitle, action, children, empty }:
  { icon: typeof Flame; title: string; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; empty?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const scroll = (dir: number) => ref.current?.scrollBy({ left: dir * ref.current.clientWidth * 0.8, behavior: "smooth" });
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-xl font-semibold text-white"><Icon className="size-5 text-aqua" /> {title}</h2>
          {subtitle && <p className="mt-1 text-sm text-zinc-400">{subtitle}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {action}
          {!empty && <>
            <button onClick={() => scroll(-1)} aria-label="Scroll left" className="hidden rounded-full border border-white/10 p-1.5 text-zinc-400 hover:border-white/25 hover:text-white sm:block"><ChevronLeft className="size-4" /></button>
            <button onClick={() => scroll(1)} aria-label="Scroll right" className="hidden rounded-full border border-white/10 p-1.5 text-zinc-400 hover:border-white/25 hover:text-white sm:block"><ChevronRight className="size-4" /></button>
          </>}
        </div>
      </div>
      {empty || (
        <div ref={ref} className="-mx-4 flex snap-x snap-mandatory gap-4 overflow-x-auto px-4 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {children}
        </div>
      )}
    </section>
  );
}

function Skeletons({ n = 6, w = "w-40 sm:w-44" }: { n?: number; w?: string }) {
  return <>{Array.from({ length: n }, (_, i) => (
    <div key={i} className={`${w} shrink-0 space-y-2`}>
      <div className="aspect-square animate-pulse rounded-xl bg-ink-800" />
      <div className="h-3 w-3/4 animate-pulse rounded bg-ink-800" /><div className="h-3 w-1/2 animate-pulse rounded bg-ink-800/70" />
    </div>
  ))}</>;
}

function CoverActions({ url, onMake }: { url: string | null; onMake: () => void }) {
  return (
    <div className="absolute inset-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/80 via-black/10 to-transparent p-2.5 transition [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:group-focus-within:opacity-100">
      <button onClick={onMake} className="inline-flex items-center gap-1.5 rounded-full bg-gradient-brand px-3 py-1.5 text-xs font-semibold text-ink-950 shadow-lg">
        <Sparkles className="size-3.5" /> Make one like this
      </button>
      {url && <a href={url} target="_blank" rel="noreferrer" title="Open in Spotify" className="rounded-full bg-black/60 p-2 text-white hover:bg-black/80"><ExternalLink className="size-3.5" /></a>}
    </div>
  );
}

export function AlbumCard({ a }: { a: Album }) {
  const make = useCreateFrom();
  return (
    <article className="group w-40 shrink-0 snap-start sm:w-44">
      <div className="relative aspect-square overflow-hidden rounded-xl bg-ink-800 shadow-xl shadow-black/30">
        {a.image ? <img src={a.image} alt="" loading="lazy" className="size-full object-cover transition duration-500 group-hover:scale-105" />
          : <Disc3 className="m-auto size-10 text-zinc-600" />}
        <CoverActions url={a.url} onMake={() => make(`Songs in the style of "${a.name}" by ${a.artists.join(", ")}: similar artists, mostly recent releases`)} />
      </div>
      <h3 className="mt-2.5 truncate text-sm font-medium text-zinc-100" title={a.name}>{a.name}</h3>
      <p className="truncate text-xs text-zinc-400">{a.artists.join(", ")}</p>
      <p className="text-xs text-zinc-600">{a.type === "single" ? "Single" : "Album"} · {formatDate(a.release_date)}</p>
    </article>
  );
}

export function IdeaCard({ p }: { p: IdeaPlaylist }) {
  const make = useCreateFrom();
  return (
    <article className="group w-44 shrink-0 snap-start sm:w-48">
      <div className="relative aspect-square overflow-hidden rounded-xl bg-ink-800 shadow-xl shadow-black/30">
        {p.image && <img src={p.image} alt="" loading="lazy" className="size-full object-cover transition duration-500 group-hover:scale-105" />}
        <span className="absolute left-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-200 backdrop-blur">{p.theme}</span>
        <CoverActions url={p.url} onMake={() => make(`${p.name}${p.description ? `: ${p.description}` : ""}`)} />
      </div>
      <h3 className="mt-2.5 truncate text-sm font-medium text-zinc-100" title={p.name}>{p.name}</h3>
      <p className="truncate text-xs text-zinc-400">{[p.owner && `by ${p.owner}`, p.followers && `${compact(p.followers)} followers`].filter(Boolean).join(" · ")}</p>
      {p.updated && <p className="text-xs text-zinc-600">{p.tracks} songs · updated {timeAgo(p.updated)}</p>}
      {p.description && <p className="mt-0.5 line-clamp-2 text-xs text-zinc-600">{p.description}</p>}
    </article>
  );
}

export function CommunityCard({ p }: { p: CommunityPlaylist }) {
  const make = useCreateFrom();
  return (
    <article className="group w-52 shrink-0 snap-start sm:w-56">
      <div className="relative grid aspect-square grid-cols-2 overflow-hidden rounded-xl bg-ink-800 shadow-xl shadow-black/30">
        {p.covers.length >= 4 ? p.covers.map((c) => <img key={c} src={c} alt="" loading="lazy" className="size-full object-cover" />)
          : p.covers[0] ? <img src={p.covers[0]} alt="" loading="lazy" className="col-span-2 size-full object-cover" /> : <Music2 className="col-span-2 m-auto size-10 text-zinc-600" />}
        {p.mine && <span className="absolute left-2 top-2 rounded-full bg-mint/90 px-2 py-0.5 text-[10px] font-bold uppercase text-ink-950">Yours</span>}
        <CoverActions url={p.url} onMake={() => make(`${p.title}${p.description ? `: ${p.description}` : ""}`)} />
      </div>
      <h3 className="mt-2.5 truncate text-sm font-medium text-zinc-100" title={p.title}>{p.title}</h3>
      <p className="truncate text-xs text-zinc-400">{p.artists.join(", ")}</p>
      <p className="text-xs text-zinc-600">{p.tracks} songs · {timeAgo(p.created_at)}</p>
    </article>
  );
}

function Trending({ tracks }: { tracks: NonNullable<DiscoverRows["rows"]["trending"]> }) {
  const top = tracks.slice(0, 10);
  const max = Math.max(...top.map((t) => t.popularity || 0), 1);
  return (
    <ol className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
      {top.map((t, i) => (
        <li key={t.id} className="group flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-white/[0.04]">
          <span className={`w-6 text-right text-sm font-bold tabular-nums ${i < 3 ? "text-gradient" : "text-zinc-600"}`}>{i + 1}</span>
          {t.image ? <img src={t.image} alt="" loading="lazy" className="size-11 rounded-md object-cover" /> : <span className="size-11 rounded-md bg-ink-800" />}
          <div className="min-w-0 flex-1">
            <a href={t.url ?? undefined} target="_blank" rel="noreferrer" className="block truncate text-sm font-medium text-zinc-100 hover:underline">{t.name}</a>
            <p className="truncate text-xs text-zinc-500">{t.artists.join(", ")}</p>
          </div>
          <div className="hidden w-16 sm:block" title={`Popularity ${t.popularity}/100`}>
            <div className="h-1 overflow-hidden rounded-full bg-ink-700"><div className="h-full bg-gradient-brand" style={{ width: `${(t.popularity / max) * 100}%` }} /></div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function Home() {
  const { me, config } = useSession();
  const make = useCreateFrom();
  const [prompt, setPrompt] = useState("");
  const [spotify, setSpotify] = useState<DiscoverRows | null>(null);
  const [community, setCommunity] = useState<{ enabled: boolean; playlists: CommunityPlaylist[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<DiscoverRows>("/discover/spotify").then(setSpotify).catch((e) => setError(String(e.message ?? e)));
    api<{ enabled: boolean; playlists: CommunityPlaylist[] }>("/discover/community").then(setCommunity).catch(() => setCommunity({ enabled: false, playlists: [] }));
  }, []);
  const rows = spotify?.rows ?? {};
  const year = new Date().getFullYear();
  const rowError = (name: string) => spotify?.errors[name] && <Notice tone="warn">Spotify didn't return this right now. Try again later.</Notice>;

  return (
    <div className="space-y-12">
      <section className="relative overflow-hidden rounded-3xl border border-white/[0.08] bg-ink-900/80 px-5 py-8 sm:px-10 sm:py-12">
        <div className="pointer-events-none absolute -right-24 -top-24 size-80 rounded-full bg-violet/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 left-10 size-80 rounded-full bg-aqua/10 blur-3xl" />
        <div className="relative max-w-2xl">
          <p className="text-sm text-zinc-400">{greeting()}, {me?.display_name.split(" ")[0]}</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-white sm:text-5xl">What are you <span className="text-gradient">in the mood for?</span></h1>
          <form className="mt-6 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); if (prompt.trim()) make(prompt.trim()); }}>
            <input className="input py-3 text-base" value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={300}
              placeholder="Describe a vibe, a moment or a few artists…" />
            <Button variant="primary" className="shrink-0 px-5 py-3" disabled={!prompt.trim()}><Wand2 className="size-4" /> Create</Button>
          </form>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {QUICK.map((q) => <button key={q} onClick={() => make(q)} className="rounded-full border border-white/10 px-3 py-1 text-xs text-zinc-400 transition hover:border-aqua/40 hover:text-white">{q}</button>)}
          </div>
        </div>
      </section>

      {error && <Notice tone="error">{error}</Notice>}
      {spotify && !spotify.connected && (
        <Notice tone="info">Connect Spotify to see new releases and playlist ideas. <Link to="/connect-spotify" className="underline">Connect now</Link></Notice>
      )}

      {(!spotify || spotify.connected) && <>
        <Shelf icon={Disc3} title="New releases" subtitle={spotify?.country ? `Out now on Spotify in ${new Intl.DisplayNames(undefined, { type: "region" }).of(spotify.country) ?? spotify.country}` : "Out now on Spotify"}
          empty={spotify && (rowError("new_releases") || (!rows.new_releases?.length && <p className="text-sm text-zinc-500">Nothing new right now.</p>))}>
          {!spotify ? <Skeletons /> : rows.new_releases?.map((a) => <AlbumCard key={a.id} a={a} />)}
        </Shelf>

        <section className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-xl font-semibold text-white"><Flame className="size-5 text-aqua" /> Popular right now</h2>
              <p className="mt-1 text-sm text-zinc-400">The most played songs released in {year}</p>
            </div>
            {!!rows.trending?.length && <button onClick={() => make(`The biggest songs of ${year} right now, mixed with similar new tracks`)} className={linkButton("secondary", "!py-2")}><Sparkles className="size-4" /> Make a playlist of these</button>}
          </div>
          {!spotify ? <div className="grid gap-2 sm:grid-cols-2">{Array.from({ length: 6 }, (_, i) => <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-850" />)}</div>
            : rowError("trending") || (rows.trending?.length ? <div className="card p-3"><Trending tracks={rows.trending} /></div> : null)}
        </section>
      </>}

      {community?.enabled && (
        <Shelf icon={Users} title="Fresh from the community" subtitle={`Playlists people made on ${config?.site_name ?? "this site"}, shared anonymously`}
          empty={!community.playlists.length && <p className="text-sm text-zinc-500">No shared playlists yet. Save one to Spotify and share it to be the first.</p>}>
          {community.playlists.map((p) => <CommunityCard key={p.id} p={p} />)}
        </Shelf>
      )}
      {!community && <Shelf icon={Users} title="Fresh from the community"><Skeletons n={5} w="w-52 sm:w-56" /></Shelf>}

      {(!spotify || spotify.connected) && (
        <Shelf icon={Lightbulb} title="Trending playlists" subtitle="Popular Spotify playlists their curators keep up to date, plus picks for today's themes."
          empty={spotify && (rowError("inspiration") || (!rows.inspiration?.length && <p className="text-sm text-zinc-500">No ideas right now.</p>))}>
          {!spotify ? <Skeletons w="w-44 sm:w-48" /> : rows.inspiration?.map((p) => <IdeaCard key={p.id} p={p} />)}
        </Shelf>
      )}
    </div>
  );
}
