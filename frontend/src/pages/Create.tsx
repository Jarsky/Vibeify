import { ArrowDown, ArrowUp, ChevronDown, ExternalLink, ListMusic, Lock, Music2, Plus, RefreshCw, Send, Sparkles, Trash2, Wand2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type Generation, type ModelOption } from "../api";
import { useSession } from "../session";
import { Button, Card, duration, Equalizer, errorText, Field, Notice, Spinner, Toggle, useToast } from "../ui";
import { Cover, PlaylistList } from "./SpotifyPlaylists";
import { UsageCard, UsageMeters } from "./Usage";

const MOODS = ["Upbeat", "Chill", "Focus", "Melancholic", "Romantic", "Energetic", "Dreamy", "Dark", "Feel-good", "Late night"];
const PROMPT_IDEAS = [
  "Sunday morning coffee, warm acoustic indie, nothing too sleepy",
  "90s and 2000s R&B for a summer barbecue",
  "Cinematic post-rock for deep work, mostly instrumental",
  "A road trip through the desert at dusk",
];
const STAGES = ["Thinking about songs…", "Finding them on Spotify…", "Putting it in order…"];

function ModelPicker({ models, value, onChange }: { models: ModelOption[]; value: string; onChange: (v: string) => void }) {
  const { config } = useSession();
  if (!models.length) return null;
  if (models.length === 1) {   // nothing to choose, but say what's being used
    const m = models[0];
    const provider = config?.provider_kinds[m.kind];
    return <p className="flex items-center gap-1.5 text-xs text-zinc-500"><Sparkles className="size-3.5 text-aqua" />
      Powered by <span className="text-zinc-300">{m.label}</span>{!m.own_key && provider && !m.label.includes(provider) && <> · {provider}</>}</p>;
  }
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
    </select>
  );
}

function useStages(active: boolean) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!active) return setI(0);
    const t = setInterval(() => setI((x) => Math.min(x + 1, STAGES.length - 1)), 6000);
    return () => clearInterval(t);
  }, [active]);
  return STAGES[i];
}

function NewPlaylistForm({ onCreated }: { onCreated: (g: Generation) => void }) {
  const { me, config, refresh } = useSession();
  const toast = useToast();
  const models = me?.models ?? [];
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"prompt" | "guided">("prompt");
  const [prompt, setPrompt] = useState(params.get("prompt")?.slice(0, 2000) ?? "");   // from the home page
  const [genres, setGenres] = useState("");
  const [artists, setArtists] = useState("");
  const [moods, setMoods] = useState<string[]>([]);
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [discovery, setDiscovery] = useState("mixed");
  const [explicit, setExplicit] = useState(true);
  const [notes, setNotes] = useState("");
  const [count, setCount] = useState(20);
  const [personalize, setPersonalize] = useState(true);
  const [model, setModel] = useState(models.find((m) => m.is_default)?.id ?? models[0]?.id ?? "");
  const [seeds, setSeeds] = useState<{ id: string; name: string; image: string | null }[]>([]);
  const [showSeeds, setShowSeeds] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const stage = useStages(busy);
  const max = me?.membership.max_playlist_size ?? config?.max_playlist_size ?? 50;
  const seedsAllowed = me?.membership.features.playlist_seeds ?? true;

  const generate = async () => {
    setBusy(true); setError("");
    try {
      const gen = await api<Generation>("/generations", { body: {
        mode, prompt, count, personalize, model: model || null, seed_playlist_ids: seeds.map((x) => x.id),
        guided: mode === "guided" ? { genres, artists, mood: moods.join(", "), notes, discovery, allow_explicit: explicit,
          year_from: yearFrom ? Number(yearFrom) : null, year_to: yearTo ? Number(yearTo) : null } : null,
      } });
      onCreated(gen);
    } catch (e) { setError(errorText(e)); toast(errorText(e), "error"); } finally { setBusy(false); refresh(); }
  };

  if (!models.length) return (
    <Notice tone="warn">No AI models are available yet. {me?.is_admin
      ? <a className="underline" href="/admin/models">Add one in the admin panel.</a>
      : config?.allow_user_llm_keys ? <Link className="underline" to="/account">Add your own API key</Link> : "Ask the site admin to add one."}</Notice>
  );

  const tabBtn = (m: typeof mode, label: string, Icon: typeof Wand2) => (
    <button onClick={() => setMode(m)} className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm transition
      ${mode === m ? "bg-ink-700 text-white shadow" : "text-zinc-400 hover:text-white"}`}><Icon className="size-4" />{label}</button>
  );

  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
     <div>
      <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">What are we listening to?</h1>
      <p className="mt-2 text-zinc-400">Describe it in your own words or build it step by step. You can refine it in chat afterwards.{" "}
        {me?.membership.features.edit_playlists && <Link to="/playlists?tab=spotify" className="text-aqua hover:underline">Or edit one of your Spotify playlists →</Link>}</p>
      <Card className="mt-8">
        <div className="mb-6 flex gap-1 rounded-xl bg-ink-850 p-1">
          {tabBtn("prompt", "Describe it", Sparkles)}
          {tabBtn("guided", "Build it", Wand2)}
        </div>
        {mode === "prompt" ? (
          <div className="space-y-3">
            <textarea className="input min-h-32 resize-y text-base" maxLength={2000} value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. Rainy evening in Tokyo, lo-fi and city pop, gets more upbeat towards the end" />
            <div className="flex flex-wrap gap-2">
              {PROMPT_IDEAS.map((p) => (
                <button key={p} onClick={() => setPrompt(p)} className="rounded-full border border-white/10 px-3 py-1 text-xs text-zinc-400 hover:border-aqua/40 hover:text-white">{p}</button>
              ))}
            </div>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Genres"><input className="input" value={genres} onChange={(e) => setGenres(e.target.value)} placeholder="indie rock, shoegaze" /></Field>
            <Field label="Artists like"><input className="input" value={artists} onChange={(e) => setArtists(e.target.value)} placeholder="Phoebe Bridgers, Alvvays" /></Field>
            <div className="sm:col-span-2">
              <span className="label">Mood</span>
              <div className="flex flex-wrap gap-2">
                {MOODS.map((m) => {
                  const on = moods.includes(m);
                  return <button key={m} onClick={() => setMoods(on ? moods.filter((x) => x !== m) : [...moods, m])}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${on ? "border-mint/50 bg-mint/15 text-white" : "border-white/10 text-zinc-400 hover:text-white"}`}>{m}</button>;
                })}
              </div>
            </div>
            <Field label="From year"><input className="input" inputMode="numeric" value={yearFrom} onChange={(e) => setYearFrom(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="Any" /></Field>
            <Field label="To year"><input className="input" inputMode="numeric" value={yearTo} onChange={(e) => setYearTo(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="Any" /></Field>
            <Field label="Discovery">
              <select className="input" value={discovery} onChange={(e) => setDiscovery(e.target.value)}>
                <option value="familiar">Mostly songs I'd know</option>
                <option value="mixed">A mix of familiar and new</option>
                <option value="new">Mostly new discoveries</option>
              </select>
            </Field>
            <div className="flex items-end pb-2"><Toggle checked={explicit} onChange={setExplicit} label="Allow explicit songs" /></div>
            <div className="sm:col-span-2">
              <Field label="Anything else"><input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="For a dinner party, no songs over 6 minutes" /></Field>
            </div>
          </div>
        )}

        <div className="mt-6 border-t border-white/[0.06] pt-5">
          {!seedsAllowed ? (
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="flex items-center gap-2 text-zinc-400"><Lock className="size-4" /> Inspired by my playlists</span>
              {config?.billing_enabled ? <Link to="/pricing" className="text-xs text-aqua hover:underline">Upgrade to unlock</Link>
                : <span className="text-xs text-zinc-500">Not included in your plan</span>}
            </div>
          ) : <>
          <button type="button" onClick={() => setShowSeeds(!showSeeds)} className="flex w-full items-center justify-between text-left">
            <span>
              <span className="flex items-center gap-2 text-sm text-zinc-100"><ListMusic className="size-4 text-aqua" /> Inspired by my playlists
                <span className="text-xs text-zinc-500">optional, up to 3</span></span>
              <span className="block text-xs text-zinc-500">Use songs from your own playlists as the style reference.</span>
            </span>
            <ChevronDown className={`size-4 text-zinc-500 transition ${showSeeds ? "rotate-180" : ""}`} />
          </button>
          {seeds.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {seeds.map((x) => (
                <span key={x.id} className="flex items-center gap-2 rounded-full border border-mint/40 bg-mint/10 py-1 pl-1 pr-2 text-sm text-white">
                  <Cover src={x.image} className="size-6 rounded-full" /> {x.name}
                  <button type="button" aria-label={`Remove ${x.name}`} onClick={() => setSeeds(seeds.filter((y) => y.id !== x.id))}><X className="size-3.5 text-zinc-400 hover:text-white" /></button>
                </span>
              ))}
            </div>
          )}
          {showSeeds && (
            <div className="mt-3 rounded-xl border border-white/10 bg-ink-850 p-2">
              <PlaylistList selected={seeds.map((x) => x.id)}
                disabled={(p) => (!seeds.some((x) => x.id === p.id) && seeds.length >= 3 ? "Up to 3 playlists" : p.total ? null : "Empty playlist")}
                onPick={(p) => setSeeds(seeds.some((x) => x.id === p.id) ? seeds.filter((x) => x.id !== p.id) : [...seeds, { id: p.id, name: p.name, image: p.image }])} />
            </div>
          )}
          </>}
        </div>

        <div className="mt-6 grid gap-5 border-t border-white/[0.06] pt-6 sm:grid-cols-2">
          <div>
            <span className="label">Songs: <span className="text-white">{count}</span></span>
            <input type="range" min={5} max={max} value={Math.min(count, max)} onChange={(e) => setCount(Number(e.target.value))} className="w-full accent-[#22d3ee]" />
          </div>
          {models.length > 1 ? <Field label="AI model"><ModelPicker models={models} value={model} onChange={setModel} /></Field>
            : <div className="self-end pb-1"><ModelPicker models={models} value={model} onChange={setModel} /></div>}
          <div className="sm:col-span-2">
            <Toggle checked={personalize} onChange={setPersonalize} label="Personalise from my listening"
              hint="Uses your top artists and recently played songs on Spotify to match your taste." />
          </div>
        </div>
        {error && <div className="mt-5"><Notice tone="error">{error}</Notice></div>}
        <Button variant="primary" className="mt-6 w-full py-3 text-base" loading={busy} onClick={generate}
          disabled={!seeds.length && (mode === "prompt" ? prompt.trim().length < 3 : !(genres || artists || moods.length || notes || yearFrom || yearTo))}>
          {busy ? stage : <><Sparkles className="size-5" /> Generate playlist</>}
        </Button>
      </Card>
     </div>
     <aside className="lg:pt-24"><UsageCard /></aside>
    </div>
  );
}

function TrackRow({ t, i, total, onMove, onRemove }: { t: Generation["tracks"][number]; i: number; total: number;
  onMove: (from: number, to: number) => void; onRemove: (i: number) => void }) {
  const s = t.spotify;
  return (
    <li className={`group flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-white/[0.03] ${s ? "" : "opacity-50"}`}>
      <span className="w-5 text-right text-xs tabular-nums text-zinc-600">{i + 1}</span>
      {s?.image ? <img src={s.image} alt="" className="size-11 rounded-md object-cover" loading="lazy" />
        : <span className="grid size-11 place-items-center rounded-md bg-ink-800"><Music2 className="size-4 text-zinc-600" /></span>}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {s?.url ? <a href={s.url} target="_blank" rel="noreferrer" className="truncate text-sm font-medium text-zinc-100 hover:underline">{s.name}</a>
            : <span className="truncate text-sm font-medium text-zinc-300">{t.title}</span>}
          {s?.explicit && <span className="rounded bg-zinc-700 px-1 text-[10px] font-bold text-zinc-300">E</span>}
        </div>
        <p className="truncate text-xs text-zinc-500">{s ? s.artists.join(", ") : `${t.artist} · not found on Spotify`}</p>
        {t.reason && <p className="hidden truncate text-xs text-zinc-600 sm:block">{t.reason}</p>}
      </div>
      {s && <span className="hidden text-xs tabular-nums text-zinc-500 sm:block">{duration(s.duration_ms)}</span>}
      <div className="flex items-center opacity-100 transition sm:opacity-0 sm:group-hover:opacity-100">
        <button title="Move up" disabled={i === 0} onClick={() => onMove(i, i - 1)} className="rounded p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white disabled:opacity-20"><ArrowUp className="size-4" /></button>
        <button title="Move down" disabled={i === total - 1} onClick={() => onMove(i, i + 1)} className="rounded p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white disabled:opacity-20"><ArrowDown className="size-4" /></button>
        <button title="Remove" onClick={() => onRemove(i)} className="rounded p-1.5 text-zinc-400 hover:bg-red-500/20 hover:text-red-300"><X className="size-4" /></button>
      </div>
    </li>
  );
}

function PlaylistEditor({ gen, setGen }: { gen: Generation; setGen: (g: Generation) => void }) {
  const { me, config, refresh } = useSession();
  const toast = useToast();
  const nav = useNavigate();
  const models = me?.models ?? [];
  const [message, setMessage] = useState("");
  const [model, setModel] = useState(models.find((m) => m.is_default)?.id ?? models[0]?.id ?? "");
  const [refining, setRefining] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isPublic, setIsPublic] = useState(false);
  const [share, setShare] = useState(true);
  const [title, setTitle] = useState(gen.title);
  const chatEnd = useRef<HTMLDivElement>(null);
  const stage = useStages(refining);
  useEffect(() => setTitle(gen.title), [gen.title]);
  useEffect(() => chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), [gen.messages.length, refining]);

  const patch = async (body: object) => {
    try { setGen(await api<Generation>(`/generations/${gen.id}`, { method: "PATCH", body })); }
    catch (e) { toast(errorText(e), "error"); }
  };
  const order = (idx: number[]) => patch({ order: idx });
  const move = (from: number, to: number) => {
    const idx = gen.tracks.map((_, i) => i);
    [idx[from], idx[to]] = [idx[to], idx[from]];
    order(idx);
  };
  const refine = async (text = message) => {
    if (!text.trim()) return;
    setRefining(true); setMessage("");
    try { setGen(await api<Generation>(`/generations/${gen.id}/refine`, { body: { message: text, model: model || null } })); }
    catch (e) { toast(errorText(e), "error"); setMessage(text); } finally { setRefining(false); refresh(); }
  };
  const save = async () => {
    setSaving(true);
    try {
      const was = gen.spotify_playlist_url;
      setGen(await api<Generation>(`/generations/${gen.id}/save`, { body: { public: isPublic, share: share && !!config?.community_feed && !gen.imported } }));
      toast(was ? "Playlist updated on Spotify" : "Saved to your Spotify library");
    } catch (e) { toast(errorText(e), "error"); } finally { setSaving(false); }
  };
  const remove = async () => {
    if (!confirm("Delete this playlist from your history? It stays in Spotify if you saved it.")) return;
    await api(`/generations/${gen.id}`, { method: "DELETE" });
    nav("/playlists");
  };

  const matched = gen.tracks.filter((t) => t.spotify);
  const total = matched.reduce((a, t) => a + (t.spotify?.duration_ms ?? 0), 0);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
      <Card className="flex flex-col lg:sticky lg:top-24 lg:h-[calc(100dvh-8rem)]">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold text-white">Refine</h2>
          <Link to="/create" className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-white"><Plus className="size-4" /> New</Link>
        </div>
        <div className="-mx-2 flex-1 space-y-3 overflow-y-auto px-2">
          {gen.messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : ""}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${m.role === "user" ? "rounded-br-sm bg-aqua/15 text-cyan-50" : "rounded-bl-sm bg-ink-800 text-zinc-200"}`}>{m.content}</div>
            </div>
          ))}
          {refining && <div className="flex items-center gap-2 text-sm text-zinc-400"><Equalizer /> {stage}</div>}
          <div ref={chatEnd} />
        </div>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {["More upbeat", "Fewer big hits", "More like the first few", "Add some 80s"].map((s) => (
            <button key={s} disabled={refining} onClick={() => refine(s)} className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-zinc-400 hover:border-aqua/40 hover:text-white disabled:opacity-40">{s}</button>
          ))}
        </div>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); refine(); }}>
          <input className="input" placeholder="Tell it what to change…" value={message} maxLength={1000} disabled={refining} onChange={(e) => setMessage(e.target.value)} />
          <Button variant="primary" className="px-3" disabled={!message.trim()} loading={refining} aria-label="Send">{!refining && <Send className="size-4" />}</Button>
        </form>
        <div className="mt-3"><ModelPicker models={models} value={model} onChange={setModel} /></div>
        {me && <div className="mt-4 border-t border-white/[0.06] pt-3"><UsageMeters usage={me.usage} small /></div>}
      </Card>

      <Card>
        <div className="flex flex-col gap-5 sm:flex-row">
          <div className="grid size-36 shrink-0 grid-cols-2 overflow-hidden rounded-xl bg-ink-800 shadow-2xl shadow-black/40">
            {matched.slice(0, 4).map((t, i) => t.spotify?.image ? <img key={i} src={t.spotify.image} alt="" className="size-full object-cover" /> : <span key={i} />)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs uppercase tracking-wider text-zinc-500">Playlist</p>
            <input className="w-full bg-transparent text-2xl font-bold text-white outline-none focus:underline decoration-white/20" value={title} maxLength={100}
              onChange={(e) => setTitle(e.target.value)} onBlur={() => title !== gen.title && patch({ title })} />
            <p className="mt-1 text-sm text-zinc-400">{gen.description}</p>
            <p className="mt-2 text-xs text-zinc-500">{[`${matched.length} songs`, `${Math.round(total / 60000)} min`, gen.request?.source_playlist ? "From your Spotify" : null, gen.model_label || null].filter(Boolean).join(" · ")}</p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button variant="spotify" loading={saving} onClick={save} disabled={!matched.length}>
                {gen.spotify_playlist_url ? <><RefreshCw className="size-4" /> Update on Spotify</> : <><Music2 className="size-4" /> Save to Spotify</>}
              </Button>
              {gen.spotify_playlist_url && <a href={gen.spotify_playlist_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 px-2 text-sm text-zinc-300 hover:text-white">Open <ExternalLink className="size-3.5" /></a>}
              {!gen.spotify_playlist_url && <label className="flex items-center gap-2 px-2 text-sm text-zinc-400"><input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} className="accent-[#2ee59d]" /> Public</label>}
              {config?.community_feed && !gen.imported && (
                <label className="flex items-center gap-2 px-2 text-sm text-zinc-400" title="Shows the title, cover art and artists to other people signed in here, never your name. Change it any time.">
                  <input type="checkbox" checked={gen.spotify_playlist_url ? gen.shared : share} className="accent-[#2ee59d]"
                    onChange={(e) => gen.spotify_playlist_url ? patch({ shared: e.target.checked }) : setShare(e.target.checked)} />
                  Share anonymously
                </label>
              )}
              <button onClick={remove} title="Delete from history" className="ml-auto rounded-lg p-2 text-zinc-500 hover:bg-red-500/10 hover:text-red-300"><Trash2 className="size-4" /></button>
            </div>
          </div>
        </div>
        {gen.tracks.length > matched.length && (
          <p className="mt-5 text-xs text-zinc-500">{gen.tracks.length - matched.length} suggested song(s) weren't found on Spotify and won't be saved.</p>
        )}
        <ol className="-mx-2 mt-4">
          {gen.tracks.map((t, i) => <TrackRow key={`${t.title}|${t.artist}`} t={t} i={i} total={gen.tracks.length} onMove={move}
            onRemove={(r) => order(gen.tracks.map((_, j) => j).filter((j) => j !== r))} />)}
        </ol>
      </Card>
    </div>
  );
}

export default function Create() {
  const { id } = useParams();
  const nav = useNavigate();
  const [gen, setGen] = useState<Generation | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setError("");
    if (!id) return setGen(null);
    if (gen?.id === id) return;
    api<Generation>(`/generations/${id}`).then(setGen).catch((e) => setError(errorText(e)));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!id) return <NewPlaylistForm onCreated={(g) => { setGen(g); nav(`/playlists/${g.id}`, { replace: false }); }} />;
  if (!gen) return <Spinner label="Loading playlist…" />;
  return <PlaylistEditor gen={gen} setGen={setGen} />;
}
