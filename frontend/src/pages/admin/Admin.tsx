import { BarChart3, Bot, CreditCard, KeyRound, LifeBuoy, Mail, ScrollText, SlidersHorizontal, Users, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../../api";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import AuditPage from "./Audit";
import Billing from "./Billing";
import Community from "./Community";
import Models from "./Models";
import Overview from "./Overview";
import SupportInbox, { SupportTicketPage } from "./Support";
import { EmailSettings, SignInSettings, SiteSettings } from "./SettingsPages";
import UserDetail from "./UserDetail";
import UsersPage from "./Users";

const TABS = [
  { to: "", label: "Overview", icon: BarChart3 },
  { to: "users", label: "Users", icon: Users },
  { to: "support", label: "Support", icon: LifeBuoy },
  { to: "audit", label: "Audit log", icon: ScrollText },
  { to: "community", label: "Community", icon: UsersRound },
  { to: "models", label: "AI models", icon: Bot },
  { to: "billing", label: "Plans & billing", icon: CreditCard },
  { to: "sign-in", label: "Sign-in & Spotify", icon: KeyRound },
  { to: "email", label: "Email", icon: Mail },
  { to: "site", label: "Site & limits", icon: SlidersHorizontal },
];

export default function Admin() {
  const { pathname } = useLocation();
  const [openTickets, setOpenTickets] = useState(0);
  useEffect(() => { api<{ counts: Record<string, number> }>("/admin/support?status=open").then((r) => setOpenTickets(r.counts.open ?? 0)).catch(() => {}); }, [pathname]);
  const tab = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition ${isActive ? "bg-white/10 text-white" : "text-zinc-400 hover:bg-white/5 hover:text-white"}`;
  return (
    <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)]">
      <aside>
        <h1 className="mb-4 hidden px-3 text-xs font-semibold uppercase tracking-wider text-zinc-500 lg:block">Admin</h1>
        <nav className="-mx-4 flex gap-1 overflow-x-auto px-4 lg:mx-0 lg:flex-col lg:px-0">
          {TABS.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={`/admin/${to}`} end={to === ""} className={tab}><Icon className="size-4" /> {label}
              {to === "support" && openTickets > 0 && <span className="ml-auto rounded-full bg-aqua/20 px-1.5 text-[11px] font-semibold text-aqua">{openTickets}</span>}</NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <Routes>
          <Route index element={<Overview />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="users/:id" element={<UserDetail />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="support" element={<SupportInbox />} />
          <Route path="support/:id" element={<SupportTicketPage />} />
          <Route path="community" element={<Community />} />
          <Route path="models" element={<Models />} />
          <Route path="billing" element={<Billing />} />
          <Route path="sign-in" element={<SignInSettings />} />
          <Route path="email" element={<EmailSettings />} />
          <Route path="site" element={<SiteSettings />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </div>
    </div>
  );
}
