import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Me, type SiteConfig } from "./api";

type SessionState = { config: SiteConfig | null; me: Me | null; loading: boolean; refresh: () => Promise<void> };
const Ctx = createContext<SessionState>({ config: null, me: null, loading: true, refresh: async () => {} });
export const useSession = () => useContext(Ctx);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const refresh = useCallback(async () => {
    const cfg = await api<SiteConfig>("/config");
    setConfig(cfg);
    document.title = cfg.site_name;
    setMe(cfg.signed_in ? await api<Me>("/me").catch(() => null) : null);
  }, []);

  const load = useCallback(() => {
    setLoading(true); setFailed(false);
    // one quiet retry covers a container restart or a blip at the proxy
    refresh().catch(() => new Promise((r) => setTimeout(r, 1500)).then(refresh)).catch(() => setFailed(true)).finally(() => setLoading(false));
  }, [refresh]);

  useEffect(load, [load]);
  if (failed) return (
    <div className="bg-glow grid min-h-dvh place-items-center px-4 text-center">
      <div>
        <p className="text-lg text-white">Can't reach the server right now.</p>
        <p className="mt-1 text-sm text-zinc-400">It may be restarting. Try again in a moment.</p>
        <button onClick={load} className="mt-5 rounded-xl bg-ink-800 px-4 py-2 text-sm text-white hover:bg-ink-700">Try again</button>
      </div>
    </div>
  );
  return <Ctx.Provider value={{ config, me, loading, refresh }}>{children}</Ctx.Provider>;
}
