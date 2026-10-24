import { Gem, History, House, LifeBuoy, LogOut, Settings, Shield, Sparkles, User } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import Account from "./pages/Account";
import Admin from "./pages/admin/Admin";
import ConnectSpotify from "./pages/ConnectSpotify";
import Create from "./pages/Create";
import Home from "./pages/Home";
import Landing from "./pages/Landing";
import Playlists from "./pages/Playlists";
import { ForgotPassword, ResetPassword, SignIn, SignUp, VerifyEmail } from "./pages/SignIn";
import { useSession } from "./session";
import Pricing from "./pages/Pricing";
import Support from "./pages/Support";
import { Equalizer, Logo, Spinner } from "./ui";

function RequireUser({ children, admin, spotify }: { children: ReactNode; admin?: boolean; spotify?: boolean }) {
  const { me, loading } = useSession();
  const loc = useLocation();
  if (loading) return <Spinner />;
  if (!me) return <Navigate to={`/signin?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (admin && !me.is_admin) return <Navigate to="/" replace />;
  if (spotify && !me.spotify) return <Navigate to="/connect-spotify" replace />;
  return <>{children}</>;
}

function SigningOut() {
  return (
    <div className="bg-glow fixed inset-0 z-50 grid place-items-center bg-ink-950/90 backdrop-blur">
      <div className="flex flex-col items-center gap-4 text-zinc-200"><Equalizer className="h-6" /><p>Signing you out…</p></div>
    </div>
  );
}

function UserMenu() {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  if (leaving) return <SigningOut />;
  if (!me) return null;
  const logout = async () => {
    setLeaving(true);
    // full page load to the home page: clears all app state, and no protected route can bounce to sign-in
    await Promise.all([api("/auth/logout", { method: "POST" }).catch(() => {}), new Promise((r) => setTimeout(r, 700))]);
    window.location.replace("/");
  };
  const item = "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-zinc-300 hover:bg-white/5 hover:text-white";
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 rounded-full border border-white/10 bg-ink-850 py-1 pl-1 pr-3 hover:border-white/20">
        {me.avatar_url
          ? <img src={me.avatar_url} alt="" className="size-7 rounded-full object-cover" />
          : <span className="grid size-7 place-items-center rounded-full bg-gradient-brand text-xs font-bold text-ink-950">{me.display_name.slice(0, 1).toUpperCase()}</span>}
        <span className="hidden max-w-32 truncate text-sm sm:block">{me.display_name}</span>
      </button>
      {open && (
        <div className="card absolute right-0 z-40 mt-2 w-52 p-1.5 shadow-2xl" onClick={() => setOpen(false)}>
          <Link to="/account" className={item}><User className="size-4" /> Account</Link>
          <Link to="/support" className={item}><LifeBuoy className="size-4" /> Help & support</Link>
          {me.is_admin && <a href="/admin" className={item}><Shield className="size-4" /> Admin</a>}
          <button onClick={logout} className={item}><LogOut className="size-4" /> Sign out</button>
        </div>
      )}
    </div>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { config, me } = useSession();
  const { pathname } = useLocation();
  const tab = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition ${isActive ? "bg-white/10 text-white" : "text-zinc-400 hover:text-white"}`;
  return (
    <div className="bg-glow flex min-h-dvh flex-col">
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-ink-950/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4">
          <Link to="/"><Logo name={config?.site_name ?? "Vibeify"} /></Link>
          {me && (
            <nav className="flex items-center gap-1">
              <NavLink to="/" end className={tab}><House className="size-4" /><span className="hidden sm:inline">Home</span></NavLink>
              <NavLink to="/create" className={tab}><Sparkles className="size-4" /><span className="hidden sm:inline">Create</span></NavLink>
              <NavLink to="/playlists" className={tab}><History className="size-4" /><span className="hidden sm:inline">My playlists</span></NavLink>
              {config?.billing_enabled && <NavLink to="/pricing" className={tab}><Gem className="size-4" /><span className="hidden sm:inline">Plans</span></NavLink>}
              {me.is_admin && (   // full page load so a proxy guarding /admin (Authentik) sees it
                <a href="/admin" className={tab({ isActive: pathname.startsWith("/admin") })}>
                  <Settings className="size-4" /><span className="hidden sm:inline">Admin</span></a>
              )}
            </nav>
          )}
          {me ? <UserMenu /> : (
            <div className="flex items-center gap-4 text-sm">
              {config?.billing_enabled && <Link to="/pricing" className="text-zinc-400 hover:text-white">Pricing</Link>}
              <Link to="/signin" className="text-zinc-300 hover:text-white">Sign in</Link>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:py-10">{children}</main>
      <footer className="border-t border-white/[0.06]">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-zinc-500">
          <span>© {new Date().getFullYear()} {config?.site_name ?? "Vibeify"} · Not affiliated with Spotify</span>
          <nav className="flex gap-5">
            {config?.billing_enabled && <Link to="/pricing" className="hover:text-white">Pricing</Link>}
            <Link to="/support" className="hover:text-white">Support</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}

export default function App() {
  const { loading, me } = useSession();
  if (loading) return <div className="bg-glow min-h-dvh"><Spinner /></div>;
  return (
    <Shell>
      <Routes>
        <Route path="/" element={me ? <Home /> : <Landing />} />
        <Route path="/signin" element={<SignIn />} />
        <Route path="/signup" element={<SignUp />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/connect-spotify" element={<ConnectSpotify />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/support" element={<Support />} />
        <Route path="/create" element={<RequireUser spotify><Create /></RequireUser>} />
        <Route path="/playlists/:id" element={<RequireUser spotify><Create /></RequireUser>} />
        <Route path="/playlists" element={<RequireUser><Playlists /></RequireUser>} />
        <Route path="/account" element={<RequireUser><Account /></RequireUser>} />
        <Route path="/admin/*" element={<RequireUser admin><Admin /></RequireUser>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
