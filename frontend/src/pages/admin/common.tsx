import { useEffect, useState } from "react";
import { api } from "../../api";
import { useSession } from "../../session";
import { errorText, useToast } from "../../ui";

export type Settings = Record<string, any>;

// Load all settings once; `save` sends only the given keys and refreshes the public config.
export function useSettings() {
  const toast = useToast();
  const { refresh } = useSession();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { api<Settings>("/admin/settings").then(setSettings).catch((e) => toast(errorText(e), "error")); }, [toast]);
  const save = async (updates: Settings) => {
    setSaving(true);
    try { setSettings(await api<Settings>("/admin/settings", { method: "PUT", body: updates })); await refresh(); toast("Settings saved"); return true; }
    catch (e) { toast(errorText(e), "error"); return false; } finally { setSaving(false); }
  };
  return { settings, setSettings, save, saving };
}

export function SecretInput({ isSet, value, onChange, placeholder }: { isSet: boolean; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return <input className="input font-mono" type="password" autoComplete="off" value={value} onChange={(e) => onChange(e.target.value)}
    placeholder={isSet ? "•••••••• (saved, type to replace)" : placeholder ?? "Not set"} />;
}
