import { Eye, EyeOff, ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { Button, Card, errorText, Spinner, timeAgo, Toggle, useToast } from "../../ui";
import { useSettings } from "./common";

type Item = { id: string; title: string; description: string; created_at: string; tracks: number; spotify_url: string | null;
  hidden: boolean; user_id: string; user_label: string };

export default function Community() {
  const toast = useToast();
  const { settings, setSettings, save, saving } = useSettings();
  const [items, setItems] = useState<Item[] | null>(null);
  const load = () => api<Item[]>("/admin/community").then(setItems).catch((e) => toast(errorText(e), "error"));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const patch = async (i: Item, body: { hidden: boolean }, ok: string) => {
    try { await api(`/admin/community/${i.id}`, { method: "PATCH", body }); toast(ok); load(); } catch (e) { toast(errorText(e), "error"); }
  };
  const toggle = (i: Item) => patch(i, { hidden: !i.hidden }, i.hidden ? "Back on the feed" : "Hidden from the feed");
  return (
    <div className="space-y-6">
      <div><h2 className="text-2xl font-semibold text-white">Community feed</h2>
        <p className="mt-1 text-sm text-zinc-400">Playlists people chose to share. The home page shows the title, description, cover art and artists, never who made it.</p></div>
      {settings && (
        <Card>
          <Toggle checked={settings.community_feed} onChange={(v) => setSettings({ ...settings, community_feed: v })} label="Show the community feed on the home page"
            hint="Off hides the row and the share option. Sharing choices are kept for when you turn it back on." />
          <Button variant="primary" className="mt-4" loading={saving} onClick={() => save({ community_feed: settings.community_feed })}>Save</Button>
        </Card>
      )}
      {!items ? <Spinner /> : (
        <section className="card overflow-hidden">
          <h2 className="px-5 pb-3 pt-5 text-base font-semibold text-white sm:px-6">Shared playlists</h2>
          {!items.length ? <p className="px-6 pb-6 text-sm text-zinc-500">Nothing shared yet.</p> : (
            <ul className="divide-y divide-white/5 border-t border-white/5">
              {items.map((i) => (
                <li key={i.id} className={`flex items-center gap-3 px-5 py-3 sm:px-6 ${i.hidden ? "opacity-60" : ""}`}>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-zinc-100">{i.title || "Untitled"} {i.hidden && <span className="ml-1 rounded bg-red-500/15 px-1.5 text-[10px] uppercase text-red-300">Hidden</span>}</p>
                    <p className="truncate text-xs text-zinc-500">{i.description}</p>
                    <p className="text-xs text-zinc-500">{i.tracks} songs · {timeAgo(i.created_at)} · by <Link to={`/admin/users/${i.user_id}`} className="text-aqua hover:underline">{i.user_label}</Link></p>
                  </div>
                  {i.spotify_url && <a href={i.spotify_url} target="_blank" rel="noreferrer" className="rounded-lg p-2 text-zinc-500 hover:bg-white/5 hover:text-white"><ExternalLink className="size-4" /></a>}
                  <Button variant="ghost" className="!px-3" onClick={() => toggle(i)}>{i.hidden ? <><Eye className="size-4" /> Show</> : <><EyeOff className="size-4" /> Hide</>}</Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
