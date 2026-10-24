import { Disc3, History, Lightbulb, MessageSquareText, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Album, type IdeaPlaylist } from "../api";
import { useSession } from "../session";
import { AlbumCard, IdeaCard, Shelf } from "./Home";
import SignInOptions from "./SignInOptions";

const FEATURES = [
  { icon: Wand2, title: "Describe the vibe", text: "Pick genres, artists, a mood and an era, or just write what you want." },
  { icon: Sparkles, title: "Made for your taste", text: "Optionally let it learn from your top artists and recent listening." },
  { icon: MessageSquareText, title: "Refine in chat", text: "“More upbeat”, “no ballads”, “swap the 90s stuff”: tweak until it's right." },
  { icon: History, title: "Saved to Spotify", text: "One click to save. Your playlists stay here to edit and re-save later." },
];

const DEMO = [
  ["Midnight City", "M83"], ["Nightcall", "Kavinsky"], ["Intro", "The xx"], ["Genesis", "Grimes"], ["Teardrop", "Massive Attack"],
];

type PublicRows = { country: string; rows: { new_releases: Album[]; inspiration: IdeaPlaylist[] } };

// Spotify's new releases and popular playlists, so visitors see music before signing in.
function OnSpotify() {
  const [data, setData] = useState<PublicRows | null>(null);
  useEffect(() => { api<PublicRows>("/discover/public").then(setData).catch(() => {}); }, []);
  if (!data || (!data.rows.new_releases.length && !data.rows.inspiration.length)) return null;
  const region = (() => { try { return new Intl.DisplayNames(undefined, { type: "region" }).of(data.country); } catch { return data.country; } })();
  return (
    <div className="space-y-12 border-t border-white/[0.06] pt-10">
      {data.rows.new_releases.length > 0 && (
        <Shelf icon={Disc3} title="New on Spotify" subtitle={`This week's releases in ${region}. Sign in to make a playlist from any of them.`}>
          {data.rows.new_releases.map((a) => <AlbumCard key={a.id} a={a} />)}
        </Shelf>
      )}
      {data.rows.inspiration.length > 0 && (
        <Shelf icon={Lightbulb} title="Trending playlists" subtitle="Popular on Spotify right now, and kept up to date.">
          {data.rows.inspiration.map((p) => <IdeaCard key={p.id} p={p} />)}
        </Shelf>
      )}
    </div>
  );
}

export default function Landing() {
  return <div className="space-y-6"><Hero /><OnSpotify /></div>;
}

function Hero() {
  const { config } = useSession();
  return (
    <div className="grid items-center gap-12 py-6 lg:grid-cols-[1.15fr_1fr] lg:py-14">
      <div>
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-zinc-300">
          <Sparkles className="size-3.5 text-mint" /> AI playlists for Spotify
        </p>
        <h1 className="text-4xl font-bold leading-[1.1] tracking-tight text-white sm:text-6xl">
          {config?.site_tagline.split(".")[0] || "Describe the vibe"}.<br />
          <span className="text-gradient">{config?.site_tagline.split(".").slice(1).join(".").trim() || "Get the playlist."}</span>
        </h1>
        <p className="mt-5 max-w-xl text-lg text-zinc-400">
          Tell {config?.site_name ?? "us"} what you're in the mood for. It picks the songs, finds them on Spotify, and lets you refine the list by chatting.
        </p>
        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div key={title} className="flex gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-ink-850"><Icon className="size-4 text-aqua" /></span>
              <div>
                <h3 className="text-sm font-semibold text-white">{title}</h3>
                <p className="text-sm text-zinc-400">{text}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="relative">
        <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-brand opacity-10 blur-3xl" />
        <div className="card p-6 sm:p-8">
          <h2 className="text-xl font-semibold text-white">Get started</h2>
          <p className="mb-6 mt-1 text-sm text-zinc-400">Free to use. Sign in, connect Spotify, and make your first playlist.</p>
          <SignInOptions />
        </div>
        <div className="card mt-5 hidden p-4 sm:block">
          <p className="mb-3 text-xs text-zinc-500">&ldquo;neon-lit late night drive, synthy, a bit melancholic&rdquo;</p>
          <ol className="space-y-2">
            {DEMO.map(([t, a], i) => (
              <li key={t} className="flex items-center gap-3 text-sm">
                <span className="w-4 text-right text-xs text-zinc-600">{i + 1}</span>
                <span className="size-8 rounded-md bg-gradient-to-br from-ink-700 to-ink-800" style={{ filter: `hue-rotate(${i * 50}deg)` }} />
                <span className="text-zinc-100">{t}</span><span className="text-zinc-500">{a}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
