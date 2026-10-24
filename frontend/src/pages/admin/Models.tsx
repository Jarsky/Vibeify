import { FlaskConical, Plus, Search, Star, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useSession } from "../../session";
import { Button, Card, errorText, Field, Notice, Spinner, Toggle, useToast } from "../../ui";

type Model = { id: string; model_id: string; display_name: string; enabled: boolean; is_default: boolean; max_output_tokens: number; sort_order: number };
export type Provider = { id: string; name: string; kind: string; base_url: string | null; enabled: boolean; key_hint: string; has_key: boolean; models: Model[] };
type Discovered = { model_id: string; display_name: string; added: boolean };

const KIND_HINT: Record<string, string> = {
  anthropic: "Key from console.anthropic.com. Claude Opus, Sonnet and Haiku are added for you.",
  openai: "Key from platform.openai.com. Use Discover to pick models your key can use.",
  gemini: "Key from aistudio.google.com. Use Discover to pick models.",
  openai_compatible: "Any server with an OpenAI-style /v1 API: Ollama, LM Studio, OpenRouter, vLLM, Groq and others.",
};

function ProviderCard({ p, reload }: { p: Provider; reload: () => Promise<void> }) {
  const toast = useToast();
  const { config } = useSession();
  const [key, setKey] = useState("");
  const [discovered, setDiscovered] = useState<Discovered[] | null>(null);
  const [filter, setFilter] = useState("");
  const [manual, setManual] = useState("");
  const [busy, setBusy] = useState("");
  const [tests, setTests] = useState<Record<string, { ok: boolean; text: string }>>({});

  const act = async (k: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(k);
    try { await fn(); await reload(); if (ok) toast(ok); } catch (e) { toast(errorText(e), "error"); } finally { setBusy(""); }
  };
  const discover = () => act("discover", async () => setDiscovered(await api<Discovered[]>(`/admin/providers/${p.id}/discover`)));
  const addModel = (model_id: string, display_name = "") => act(`add:${model_id}`, async () => {
    await api(`/admin/providers/${p.id}/models`, { body: { model_id, display_name } });
    setDiscovered((d) => d?.map((x) => (x.model_id === model_id ? { ...x, added: true } : x)) ?? null);
  });
  const patchModel = (m: Model, body: object) => act(`m:${m.id}`, () => api(`/admin/models/${m.id}`, { method: "PATCH", body }));
  const test = async (m: Model) => {
    setBusy(`test:${m.id}`);
    try {
      const r = await api<{ seconds: number; tracks: string[]; output_tokens: number }>(`/admin/models/${m.id}/test`, { method: "POST" });
      setTests((t) => ({ ...t, [m.id]: { ok: true, text: `Works · ${r.seconds}s · ${r.tracks.join(" · ")}` } }));
    } catch (e) { setTests((t) => ({ ...t, [m.id]: { ok: false, text: errorText(e) } })); } finally { setBusy(""); }
  };

  return (
    <Card title={<span className="flex items-center gap-3">{p.name}<span className="rounded-full bg-ink-700 px-2 py-0.5 text-xs font-normal text-zinc-400">{config?.provider_kinds[p.kind]}</span></span>}
      actions={<Toggle checked={p.enabled} onChange={(v) => act("enable", () => api(`/admin/providers/${p.id}`, { method: "PATCH", body: { enabled: v } }))} label="" />}>
      <div className="mb-5 grid gap-3 sm:grid-cols-[1fr_auto]">
        <input className="input font-mono" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={p.has_key ? `Key saved (${p.key_hint}). Type to replace` : "API key"} />
        <Button disabled={!key} loading={busy === "key"} onClick={() => act("key", () => api(`/admin/providers/${p.id}`, { method: "PATCH", body: { api_key: key } }), "Key updated").then(() => setKey(""))}>Save key</Button>
      </div>
      {p.base_url && <p className="-mt-2 mb-5 text-xs text-zinc-500">Base URL: {p.base_url}</p>}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm">
          <thead><tr className="text-left text-xs text-zinc-500"><th className="pb-2 font-medium">Shown as</th><th className="pb-2 font-medium">Model ID</th><th className="pb-2 font-medium">On</th><th className="pb-2 font-medium">Default</th><th /></tr></thead>
          <tbody className="divide-y divide-white/5">
            {p.models.map((m) => (
              <tr key={m.id} className="align-top">
                <td className="py-2 pr-3">
                  <input className="w-full rounded bg-transparent px-1 py-0.5 text-zinc-100 outline-none hover:bg-white/5 focus:bg-ink-800" defaultValue={m.display_name}
                    onBlur={(e) => e.target.value !== m.display_name && patchModel(m, { display_name: e.target.value })} />
                  {tests[m.id] && <p className={`mt-1 px-1 text-xs ${tests[m.id].ok ? "text-mint" : "text-red-300"}`}>{tests[m.id].text}</p>}
                </td>
                <td className="py-2 pr-3 font-mono text-xs text-zinc-400">{m.model_id}</td>
                <td className="py-2"><input type="checkbox" className="accent-[#2ee59d]" checked={m.enabled} onChange={(e) => patchModel(m, { enabled: e.target.checked })} /></td>
                <td className="py-2"><button title="Make default" onClick={() => patchModel(m, { is_default: true })}><Star className={`size-4 ${m.is_default ? "fill-amber-300 text-amber-300" : "text-zinc-600 hover:text-zinc-300"}`} /></button></td>
                <td className="whitespace-nowrap py-1 text-right">
                  <Button variant="ghost" className="px-2 py-1.5" title="Send a small test request" loading={busy === `test:${m.id}`} onClick={() => test(m)}><FlaskConical className="size-4" /></Button>
                  <Button variant="ghost" className="px-2 py-1.5" title="Remove" onClick={() => act(`del:${m.id}`, () => api(`/admin/models/${m.id}`, { method: "DELETE" }))}><Trash2 className="size-4" /></Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!p.models.length && <p className="py-3 text-sm text-zinc-500">No models yet. Discover them or add one by ID.</p>}
      </div>

      <div className="mt-5 flex flex-wrap gap-2 border-t border-white/[0.06] pt-5">
        <Button loading={busy === "discover"} onClick={discover}><Search className="size-4" /> Discover models</Button>
        <form className="flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); addModel(manual.trim()).then(() => setManual("")); }}>
          <input className="input min-w-40" value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Add by model ID" />
          <Button disabled={!manual.trim()}><Plus className="size-4" /></Button>
        </form>
        <Button variant="danger" onClick={() => confirm(`Delete ${p.name} and its models?`) && act("delete", () => api(`/admin/providers/${p.id}`, { method: "DELETE" }))}><Trash2 className="size-4" /></Button>
      </div>
      {discovered && (
        <div className="mt-4 rounded-xl border border-white/10 bg-ink-850 p-3">
          <input className="input mb-3" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={`Filter ${discovered.length} models`} />
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {discovered.filter((d) => (d.model_id + d.display_name).toLowerCase().includes(filter.toLowerCase())).map((d) => (
              <li key={d.model_id} className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 hover:bg-white/5">
                <span className="min-w-0"><span className="block truncate text-sm text-zinc-200">{d.display_name}</span><span className="block truncate font-mono text-xs text-zinc-500">{d.model_id}</span></span>
                {d.added ? <span className="text-xs text-mint">Added</span>
                  : <Button className="px-3 py-1 text-xs" loading={busy === `add:${d.model_id}`} onClick={() => addModel(d.model_id, d.display_name)}>Add</Button>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

export default function Models() {
  const { config, refresh } = useSession();
  const toast = useToast();
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [kind, setKind] = useState("anthropic");
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const reload = useCallback(async () => { setProviders(await api<Provider[]>("/admin/providers")); await refresh(); }, [refresh]);
  useEffect(() => { reload().catch((e) => toast(errorText(e), "error")); }, [reload, toast]);
  if (!providers || !config) return <Spinner />;

  const create = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true);
    try {
      await api("/admin/providers", { body: { kind, name: name || config.provider_kinds[kind], api_key: key || null, base_url: kind === "openai_compatible" ? baseUrl : null } });
      setName(""); setKey(""); setBaseUrl(""); await reload(); toast("Provider added");
    } catch (err) { toast(errorText(err), "error"); } finally { setBusy(false); }
  };
  const noDefault = providers.every((p) => p.models.every((m) => !m.is_default || !m.enabled));

  return (
    <div className="space-y-6">
      <div><h2 className="text-2xl font-semibold text-white">AI models</h2>
        <p className="mt-1 text-sm text-zinc-400">Providers use your API keys. Users choose between the enabled models, and the starred one is the default.</p></div>
      {providers.some((p) => p.kind === "anthropic") && (
        <Notice>Claude requests use server-side fallbacks: if a model declines a request, Anthropic automatically retries it on a fallback model so the user still gets a playlist.</Notice>
      )}
      {noDefault && providers.some((p) => p.models.length) && <Notice tone="warn">No default model is set. Star one so new users get a sensible choice.</Notice>}
      {providers.map((p) => <ProviderCard key={p.id} p={p} reload={reload} />)}
      <Card title="Add a provider">
        <form onSubmit={create} className="grid gap-4 sm:grid-cols-2">
          <Field label="Type">
            <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(config.provider_kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={config.provider_kinds[kind]} /></Field>
          {kind === "openai_compatible" && <div className="sm:col-span-2"><Field label="Base URL"><input className="input" required value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://ollama:11434/v1" /></Field></div>}
          <div className="sm:col-span-2"><Field label="API key" hint={KIND_HINT[kind]}>
            <input className="input font-mono" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} required={kind !== "openai_compatible"} /></Field></div>
          <div><Button variant="primary" loading={busy}><Plus className="size-4" /> Add provider</Button></div>
        </form>
      </Card>
    </div>
  );
}
