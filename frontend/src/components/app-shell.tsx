"use client";

import clsx from "clsx";
import {
  BarChart3,
  Bell,
  Bot,
  Briefcase,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  PauseCircle,
  Search,
  Send,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import type { Notification, User } from "@/lib/types";
import { Button, Spinner } from "./ui";
import { useToast } from "./ui/toast";

const NAV = [
  { href: "/", label: "Обзор", icon: LayoutDashboard },
  { href: "/vacancies", label: "Вакансии", icon: Briefcase },
  { href: "/applications", label: "Отклики", icon: Send },
  { href: "/resumes", label: "Резюме", icon: FileText },
  { href: "/search-profiles", label: "Профили поиска", icon: Search },
  { href: "/automation", label: "Автоматизация", icon: Bot },
  { href: "/analytics", label: "Аналитика", icon: BarChart3 },
  { href: "/settings", label: "Настройки", icon: Settings },
];

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext);

export function AppShell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [unread, setUnread] = useState<Notification[]>([]);
  const [menu, setMenu] = useState(false);
  const [bell, setBell] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();

  useEffect(() => {
    api
      .get<User>("/api/auth/me")
      .then(setUser)
      .catch(() => router.replace(`/login?next=${encodeURIComponent(pathname)}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!user) return;
    const load = () =>
      api
        .get<{ items: Notification[] }>("/api/notifications?unread_only=true&limit=20")
        .then((r) => setUnread(r.items))
        .catch(() => {});
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [user, pathname]);

  useEffect(() => setMenu(false), [pathname]);

  if (!user) return <Spinner />;

  const pauseAll = async () => {
    try {
      const r = await api.post<{ returned_to_confirmation: number }>("/api/automation/stop-all");
      toast(`Всё остановлено. Вернули на подтверждение: ${r.returned_to_confirmation}`, "ok");
    } catch (e) {
      toast(errorMessage(e), "bad");
    }
  };

  const logout = async () => {
    await api.post("/api/auth/logout").catch(() => {});
    router.replace("/login");
  };

  const readAll = async () => {
    await api.post("/api/notifications/read-all").catch(() => {});
    setUnread([]);
    setBell(false);
  };

  return (
    <UserContext.Provider value={user}>
      <div className="flex min-h-screen">
        <aside
          className={clsx(
            "fixed inset-y-0 left-0 z-40 w-60 shrink-0 border-r border-border bg-surface p-4 transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0",
            menu ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <Link href="/" className="mb-6 block px-2 text-lg font-semibold">
            Ashore<span className="text-brand">.</span>
          </Link>
          <nav className="flex flex-col gap-0.5">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={clsx(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm",
                    active ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-bg hover:text-ink",
                  )}
                >
                  <Icon className="size-4" />
                  {label}
                </Link>
              );
            })}
          </nav>
          <div className="absolute inset-x-4 bottom-4">
            <div className="truncate px-2 text-xs text-muted">{user.email}</div>
            <button onClick={logout} className="mt-2 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-bg">
              <LogOut className="size-4" /> Выйти
            </button>
          </div>
        </aside>
        {menu && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setMenu(false)} />}

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-surface/90 px-4 backdrop-blur">
            <button className="md:hidden" onClick={() => setMenu(true)} aria-label="Меню">
              <Menu className="size-5" />
            </button>
            <div className="flex-1" />
            <Button variant="secondary" size="sm" onClick={pauseAll} title="Остановить всю автоматизацию и очередь">
              <PauseCircle className="size-4" /> Остановить всё
            </Button>
            <div className="relative">
              <button onClick={() => setBell((v) => !v)} className="relative rounded-lg p-2 hover:bg-bg" aria-label="Уведомления">
                <Bell className="size-5" />
                {unread.length > 0 && (
                  <span className="absolute right-1 top-1 grid size-4 place-items-center rounded-full bg-bad text-[10px] text-white">
                    {unread.length > 9 ? "9+" : unread.length}
                  </span>
                )}
              </button>
              {bell && (
                <div className="absolute right-0 top-11 w-80 rounded-xl border border-border bg-surface p-2 shadow-xl">
                  {unread.length === 0 ? (
                    <div className="p-4 text-center text-sm text-muted">Новых уведомлений нет</div>
                  ) : (
                    <>
                      <div className="max-h-96 overflow-y-auto">
                        {unread.map((n) => (
                          <div key={n.id} className="rounded-lg px-3 py-2 hover:bg-bg">
                            <div className="text-sm font-medium">{n.title}</div>
                            {n.body && <div className="text-xs text-muted">{n.body}</div>}
                          </div>
                        ))}
                      </div>
                      <button onClick={readAll} className="mt-1 w-full rounded-lg py-2 text-sm text-brand hover:bg-bg">
                        Отметить все прочитанными
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          </header>
          <main className="mx-auto max-w-6xl p-4 md:p-6">{children}</main>
        </div>
      </div>
    </UserContext.Provider>
  );
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
