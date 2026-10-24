import { Loader2 } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "spotify";
const variants: Record<Variant, string> = {
  primary: "bg-gradient-brand text-ink-950 font-semibold hover:brightness-110 shadow-lg shadow-aqua/10",
  secondary: "bg-ink-800 text-zinc-100 border border-white/10 hover:bg-ink-700",
  ghost: "text-zinc-300 hover:bg-white/5 hover:text-white",
  danger: "bg-red-500/10 text-red-300 border border-red-500/30 hover:bg-red-500/20",
  spotify: "bg-[#1ed760] text-black font-semibold hover:bg-[#3be477]",
};

export function Button({ variant = "secondary", loading, className = "", children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button {...rest} disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm transition
        disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}>
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export const linkButton = (variant: Variant = "secondary", extra = "") =>
  `inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm transition ${variants[variant]} ${extra}`;

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export function Toggle({ checked, onChange, label, hint, disabled }:
  { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; hint?: ReactNode; disabled?: boolean }) {
  return (
    <label className={`flex items-start gap-3 ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition ${checked ? "bg-mint" : "bg-ink-600"}`}>
        <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${checked ? "left-5.5" : "left-0.5"}`} />
      </button>
      <span>
        <span className="block text-sm text-zinc-100">{label}</span>
        {hint && <span className="block text-xs text-zinc-500">{hint}</span>}
      </span>
    </label>
  );
}

export function Card({ title, actions, children, className = "" }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-5 sm:p-6 ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-base font-semibold text-white">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "success" | "warn"; children: ReactNode }) {
  const tones = {
    info: "border-aqua/30 bg-aqua/5 text-cyan-100",
    error: "border-red-500/30 bg-red-500/10 text-red-200",
    success: "border-mint/30 bg-mint/10 text-emerald-100",
    warn: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  };
  return <div className={`rounded-xl border px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>;
}

export function Equalizer({ className = "" }: { className?: string }) {
  return (
    <span className={`eq inline-flex h-4 items-end gap-0.5 ${className}`} aria-hidden>
      {[0, 1, 2, 3].map((i) => <span key={i} className="h-full w-1 rounded-full bg-gradient-brand" />)}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-sm text-zinc-400">
      <Equalizer /> {label ?? "Loading…"}
    </div>
  );
}

export function Logo({ name }: { name: string }) {
  return (
    <span className="flex items-center gap-2.5 font-semibold tracking-tight text-white">
      <img src="/favicon.svg" alt="" className="size-7" />
      <span className="text-lg">{name}</span>
    </span>
  );
}

// ── toasts ───────────────────────────────────────────────────────────────────
type Toast = { id: number; text: string; tone: "success" | "error" };
const ToastCtx = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
        {toasts.map((t) => (
          <div key={t.id} className={`pointer-events-auto max-w-md rounded-xl border px-4 py-2.5 text-sm shadow-2xl backdrop-blur
            ${t.tone === "error" ? "border-red-500/40 bg-red-950/90 text-red-100" : "border-mint/30 bg-ink-800/95 text-zinc-100"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function duration(ms: number) {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export function timeAgo(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  const [n, unit] = s < 3600 ? [s / 60, "min"] : s < 86400 ? [s / 3600, "h"] : s < 86400 * 30 ? [s / 86400, "d"] : [0, ""];
  return unit ? `${Math.floor(n)}${unit === "min" ? " min" : unit} ago` : formatDate(iso);
}
