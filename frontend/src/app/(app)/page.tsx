"use client";

import { ArrowRight, Briefcase, CheckCircle2, CircleAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/app-shell";
import { Alert, Badge, Button, Card, CardTitle, Spinner, Stat } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { CAPABILITY_LABEL, CAPABILITY_STATUS_LABEL, dateTime, percent } from "@/lib/format";
import type { Capability, Notification, Overview, Visibility } from "@/lib/types";
import { VisibilitySummary } from "@/components/visibility";
import { useApi } from "@/lib/use-api";

interface Dashboard {
  today: Overview;
  week: Overview;
  decisions: Record<string, number>;
  applications: Record<string, number>;
  awaiting_confirmation: number;
  unknown: number;
  automation: { mode: string; paused: boolean; paused_reason: string | null; auto_active: boolean; sent_today: number; daily_limit: number };
  hh: { configured: boolean; connected: boolean; capabilities: Record<string, Capability> };
  resume: { id: string; title: string; visibility: Visibility } | null;
  notifications: Notification[];
  demo_mode: boolean;
}

const MODE_LABEL: Record<string, string> = { manual: "Ручной", assisted: "С подтверждением", auto: "Автоотклики" };

export default function DashboardPage() {
  const { data, loading, reload } = useApi<Dashboard>("/api/dashboard");
  const toast = useToast();
  if (loading && !data) return <Spinner />;
  if (!data) return <Alert tone="bad">Не удалось загрузить обзор</Alert>;

  const seed = async () => {
    try {
      const r = await api.post<{ vacancies: number }>("/api/demo/seed");
      toast(`Добавлено примеров: ${r.vacancies}`, "ok");
      reload();
    } catch (e) {
      toast(errorMessage(e), "bad");
    }
  };

  const suitable = (data.decisions.eligible ?? 0) + (data.decisions.ready_to_apply ?? 0);
  const review = data.decisions.review ?? 0;

  return (
    <>
      <PageHeader title="Обзор" description="Что происходит с поиском работы сегодня" />

      {!data.resume && (
        <div className="mb-6">
          <Alert tone="brand" title="Начните с резюме">
            Загрузите резюме (PDF или DOCX, можно скачать с hh.ru), проверьте извлечённые навыки, и Ashore начнёт оценивать вакансии.{" "}
            <Link href="/resumes" className="text-brand">
              Загрузить резюме →
            </Link>
          </Alert>
        </div>
      )}

      {data.automation.paused && (
        <div className="mb-6">
          <Alert tone="warn" title="Автоматизация на паузе">
            {data.automation.paused_reason}{" "}
            <Link href="/automation" className="text-brand">
              Открыть настройки →
            </Link>
          </Alert>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Найдено сегодня" value={data.today.found} hint={`за неделю ${data.week.found}`} />
        <Stat label="Подходит" value={suitable} hint={`ещё ${review} на проверку`} />
        <Stat label="Откликов сегодня" value={data.today.sent} hint={`лимит ${data.automation.daily_limit}`} />
        <Stat label="Приглашений за неделю" value={data.week.invitations} hint={`конверсия ${percent(data.week.invitation_rate)}`} />
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Card>
          <CardTitle>Требует внимания</CardTitle>
          <div className="space-y-2">
            <ActionRow
              href="/applications?status=awaiting_confirmation"
              icon={<CheckCircle2 className="size-4 text-brand" />}
              label="Отклики ждут подтверждения"
              count={data.awaiting_confirmation}
            />
            <ActionRow
              href="/vacancies?decision=review"
              icon={<Briefcase className="size-4 text-warn" />}
              label="Вакансии на проверку"
              count={review}
            />
            <ActionRow
              href="/applications?status=unknown"
              icon={<CircleAlert className="size-4 text-bad" />}
              label="Проверить отправку на hh.ru"
              count={data.unknown}
            />
          </div>
        </Card>

        <Card>
          <CardTitle action={<Link href="/settings" className="text-sm text-brand">Настроить</Link>}>hh.ru</CardTitle>
          {!data.hh.connected ? (
            <p className="text-sm text-muted">
              Аккаунт hh.ru не подключён через API. Работает основной режим: вакансии добавляются кнопкой-закладкой или вручную,
              отклик отправляется на сайте hh.ru в один клик с готовым письмом.
            </p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {Object.entries(data.hh.capabilities).map(([key, cap]) => (
                <li key={key} className="flex justify-between">
                  <span>{CAPABILITY_LABEL[key] ?? key}</span>
                  <Badge tone={cap.status === "verified" ? "ok" : cap.status === "unavailable" ? "bad" : "neutral"}>
                    {CAPABILITY_STATUS_LABEL[cap.status]}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 text-xs text-muted">
            Режим: {MODE_LABEL[data.automation.mode]}
            {data.automation.auto_active && " · автоотклики активны"}
          </div>
        </Card>

        {data.resume && (
          <Card>
            <CardTitle action={<Link href={`/resumes/${data.resume.id}`} className="text-sm text-brand">Открыть</Link>}>
              Видимость резюме
            </CardTitle>
            <VisibilitySummary v={data.resume.visibility} />
          </Card>
        )}

        <Card>
          <CardTitle>Последние события</CardTitle>
          {data.notifications.length === 0 ? (
            <p className="text-sm text-muted">Новых уведомлений нет.</p>
          ) : (
            <ul className="space-y-2">
              {data.notifications.map((n) => (
                <li key={n.id} className="text-sm">
                  <div className="font-medium">{n.title}</div>
                  <div className="text-xs text-muted">{dateTime(n.created_at)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {data.demo_mode && (
        <Card className="mt-6">
          <CardTitle>Демо-данные</CardTitle>
          <p className="mb-3 text-sm text-muted">
            Добавить шесть примеров вакансий (помечены «Пример»), чтобы посмотреть, как работают оценка, письма и очередь откликов.
            Это не настоящие вакансии hh.ru.
          </p>
          <Button variant="secondary" onClick={seed}>
            <Sparkles className="size-4" /> Загрузить примеры
          </Button>
        </Card>
      )}
    </>
  );
}

function ActionRow({ href, icon, label, count }: { href: string; icon: React.ReactNode; label: string; count: number }) {
  return (
    <Link href={href} className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm hover:bg-bg">
      {icon}
      <span className="flex-1">{label}</span>
      <span className="font-semibold tabular-nums">{count}</span>
      <ArrowRight className="size-4 text-muted" />
    </Link>
  );
}
