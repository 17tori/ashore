"use client";

import { Pause, Play, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Alert, Badge, Button, Card, CardTitle, Dialog, Field, Input, Spinner } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { AutomationState, Resume } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const MODES = [
  { value: "manual", title: "Ручной", text: "Ashore оценивает вакансии и готовит письма по кнопке. Всё отправляете вы." },
  { value: "assisted", title: "С подтверждением", text: "Подходящие вакансии сами попадают в очередь с готовым письмом. Отправка только после вашего «да»." },
  { value: "auto", title: "Автоотклики", text: "Отправка без подтверждения, строго по вашим правилам. Нужен подтверждённый доступ к API hh.ru." },
] as const;

const JOB_LABEL: Record<string, string> = {
  discover: "Поиск вакансий",
  process_queue: "Очередь откликов",
  sync_negotiations: "Статусы откликов",
  check_oauth: "Проверка доступа hh.ru",
  visibility: "Поднятие резюме",
  daily_report: "Ежедневная сводка",
};

const ACTION_LABEL: Record<string, string> = {
  "auth.registered": "Регистрация",
  "auth.login": "Вход",
  "resume.created": "Резюме загружено",
  "resume.version_created": "Новая версия резюме",
  "resume.archived": "Резюме в архиве",
  "resume.manual_publish_marked": "Резюме поднято вручную",
  "vacancy.imported": "Вакансия добавлена",
  "match.decision_overridden": "Ваше решение по вакансии",
  "employer.excluded": "Компания в стоп-листе",
  "application.approved": "Отклик подтверждён",
  "application.sent": "Отклик отправлен через hh.ru",
  "application.marked_sent": "Отклик отмечен отправленным",
  "application.unknown": "Результат отправки неизвестен",
  "automation.policy_updated": "Правила изменены",
  "automation.auto_confirmed": "Автоотклики включены",
  "automation.auto_disabled": "Автоотклики выключены",
  "automation.paused": "Пауза",
  "automation.resumed": "Возобновлено",
  "hh.connected": "hh.ru подключён",
  "hh.disconnected": "hh.ru отключён",
  "consent.ai_external": "Согласие на AI изменено",
  "telegram.linked": "Telegram привязан",
  "telegram.unlinked": "Telegram отвязан",
  "demo.seeded": "Загружены примеры",
  "account.exported": "Выгрузка данных",
};
const ACTOR_LABEL: Record<string, string> = { user: "вы", system: "система", telegram: "Telegram", platform: "hh.ru", ai: "AI" };

interface LogEntry {
  id: string;
  action: string;
  actor: string;
  details: Record<string, unknown>;
  at: string;
}

export default function AutomationPage() {
  const { data: state, loading, setData } = useApi<AutomationState>("/api/automation");
  const { data: resumes } = useApi<Resume[]>("/api/resumes");
  const { data: jobs } = useApi<any[]>("/api/automation/jobs");
  const { data: log, reload: reloadLog } = useApi<LogEntry[]>("/api/automation/log?limit=50");
  const [rules, setRules] = useState({ positions: "", min_score: 75, daily_limit: 10, salary_min: "" });
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    if (!state) return;
    setRules({
      positions: state.allowed_positions.join(", "),
      min_score: state.min_score,
      daily_limit: state.daily_limit,
      salary_min: state.salary_min ? String(state.salary_min) : "",
    });
  }, [state?.rules_hash]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading && !state) return <Spinner />;
  if (!state) return <Alert tone="bad">Не удалось загрузить настройки</Alert>;

  const act = async (key: string, fn: () => Promise<AutomationState | void>) => {
    setBusy(key);
    try {
      const next = await fn();
      if (next) setData(next);
      reloadLog();
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(null);
    }
  };

  const patch = (body: Record<string, unknown>) => act("patch", () => api.patch<AutomationState>("/api/automation/policy", body));
  const saveRules = () =>
    patch({
      allowed_positions: rules.positions.split(",").map((x) => x.trim()).filter(Boolean),
      min_score: Number(rules.min_score),
      daily_limit: Number(rules.daily_limit),
      salary_min: rules.salary_min ? Number(rules.salary_min) : null,
    });
  const toggleResume = (id: string) => {
    const ids = new Set(state.allowed_resume_ids);
    if (ids.has(id)) ids.delete(id);
    else ids.add(id);
    patch({ allowed_resume_ids: [...ids] });
  };
  const chooseMode = (mode: string) => {
    if (mode === "auto") {
      setAck(false);
      setConfirmOpen(true);
    } else if (state.mode === "auto") {
      act("mode", () => api.post<AutomationState>(`/api/automation/disable-auto?mode=${mode}`));
    } else {
      patch({ mode });
    }
  };
  const confirmAuto = () =>
    act("confirm", async () => {
      const next = await api.post<AutomationState>("/api/automation/confirm-auto", { rules_hash: state.rules_hash, acknowledged: ack });
      setConfirmOpen(false);
      return next;
    });

  return (
    <>
      <PageHeader
        title="Автоматизация"
        description="Сколько решений Ashore принимает сам. Остановить всё можно в любой момент кнопкой вверху."
        actions={
          state.paused ? (
            <Button onClick={() => act("resume", () => api.post<AutomationState>("/api/automation/resume"))} loading={busy === "resume"}>
              <Play className="size-4" /> Возобновить
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => act("pause", () => api.post<AutomationState>("/api/automation/pause"))} loading={busy === "pause"}>
              <Pause className="size-4" /> Пауза
            </Button>
          )
        }
      />

      {state.paused && (
        <div className="mb-4">
          <Alert tone="warn" title="На паузе">
            {state.paused_reason}
          </Alert>
        </div>
      )}
      {state.mode === "auto" && !state.auto_active && !state.paused && (
        <div className="mb-4">
          <Alert tone="warn" title="Автоотклики не отправляются">
            Правила изменились после подтверждения. Подтвердите их заново, чтобы автоотклики возобновились.
          </Alert>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3">
        {MODES.map((m) => (
          <button
            key={m.value}
            onClick={() => chooseMode(m.value)}
            className={`rounded-xl border p-4 text-left transition-colors ${state.mode === m.value ? "border-brand bg-brand/5" : "border-border bg-surface hover:border-brand/40"}`}
          >
            <div className="flex items-center gap-2 font-medium">
              {m.title}
              {state.mode === m.value && <Badge tone="brand">включён</Badge>}
            </div>
            <p className="mt-1 text-sm text-muted">{m.text}</p>
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Правила автооткликов</CardTitle>
          <div className="space-y-4">
            <Field label="Разрешённые должности" hint="Через запятую. Отклик только если название вакансии похоже на одну из них.">
              <Input value={rules.positions} onChange={(e) => setRules({ ...rules, positions: e.target.value })} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Мин. оценка">
                <Input type="number" min={50} max={100} value={rules.min_score} onChange={(e) => setRules({ ...rules, min_score: Number(e.target.value) })} />
              </Field>
              <Field label={`В день (до ${state.hard_daily_cap})`}>
                <Input type="number" min={1} max={state.hard_daily_cap} value={rules.daily_limit} onChange={(e) => setRules({ ...rules, daily_limit: Number(e.target.value) })} />
              </Field>
              <Field label="Зарплата от">
                <Input type="number" value={rules.salary_min} onChange={(e) => setRules({ ...rules, salary_min: e.target.value })} />
              </Field>
            </div>
            <div>
              <div className="mb-2 text-sm font-medium">Резюме для автооткликов</div>
              <div className="space-y-1">
                {resumes?.map((r) => (
                  <label key={r.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={state.allowed_resume_ids.includes(r.id)} onChange={() => toggleResume(r.id)} />
                    {r.title} {!r.hh_resume_id && <span className="text-xs text-muted">(не связано с hh.ru)</span>}
                  </label>
                ))}
              </div>
            </div>
            <Button variant="secondary" onClick={saveRules} loading={busy === "patch"}>
              Сохранить правила
            </Button>
            {state.auto_problems.length > 0 && (
              <Alert tone="warn" title="Чтобы включить автоотклики:">
                <ul className="list-disc pl-5">
                  {state.auto_problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </Alert>
            )}
          </div>
        </Card>

        <Card>
          <CardTitle>Сегодня</CardTitle>
          <div className="space-y-1.5 text-sm">
            <Row label="Отправлено" value={`${state.sent_today} из ${state.daily_limit}`} />
            <Row label="Окно отправки" value={state.in_apply_window ? "открыто" : "закрыто"} />
            <Row label="Правила подтверждены" value={state.confirmed_at ? dateTime(state.confirmed_at) : "нет"} />
            <Row label="Автоотклики" value={state.auto_active ? "активны" : "не активны"} />
          </div>
          <div className="mt-5 text-sm font-medium">Остановки</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
            <li>капча на hh.ru — пауза сразу</li>
            <li>истёк доступ к hh.ru — пауза</li>
            <li>{state.stop_conditions.max_consecutive_failures ?? 3} ошибки отправки подряд — пауза</li>
            <li>лимит откликов hh.ru — пауза до следующего дня</li>
          </ul>
          {jobs && jobs.length > 0 && (
            <>
              <div className="mt-5 text-sm font-medium">Фоновые задачи</div>
              <ul className="mt-2 space-y-1 text-sm">
                {jobs.map((j) => (
                  <li key={j.id} className="flex justify-between gap-2">
                    <span>{JOB_LABEL[j.kind] ?? j.kind}</span>
                    <span className="text-muted">{j.last_status === "error" ? "ошибка" : `след. ${dateTime(j.next_run_at)}`}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <CardTitle>Журнал действий</CardTitle>
        {!log || log.length === 0 ? (
          <p className="text-sm text-muted">Пока пусто.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {log.map((e) => (
              <li key={e.id} className="flex gap-3">
                <span className="w-32 shrink-0 text-muted">{dateTime(e.at)}</span>
                <span className="w-20 shrink-0 text-muted">{ACTOR_LABEL[e.actor] ?? e.actor}</span>
                <span>{ACTION_LABEL[e.action] ?? e.action}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} title="Включить автоотклики">
        <div className="space-y-3 text-sm">
          <p>Ashore будет отправлять отклики без вашего подтверждения, только если выполнены все условия:</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>должность похожа на: {state.allowed_positions.join(", ") || "—"}</li>
            <li>оценка не ниже {state.min_score}</li>
            <li>не больше {state.daily_limit} откликов в день</li>
            {state.salary_min && <li>зарплата от {state.salary_min.toLocaleString("ru-RU")} ₽ (если указана)</li>}
            <li>резюме: {state.allowed_resume_ids.length} выбрано</li>
            <li>письмо проходит проверку фактов</li>
            <li>hh.ru подтвердил, что отклики через API для вашего аккаунта работают</li>
          </ul>
          <p className="text-muted">Любое изменение правил выключит автоотклики до нового подтверждения.</p>
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            Я проверил(а) правила и разрешаю отправку по ним
          </label>
          {state.auto_problems.length > 0 && <Alert tone="bad">{state.auto_problems.join("; ")}</Alert>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Отмена
            </Button>
            <Button onClick={confirmAuto} disabled={!ack || state.auto_problems.length > 0} loading={busy === "confirm"}>
              <ShieldCheck className="size-4" /> Включить
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted">{label}</span>
      <span>{value}</span>
    </div>
  );
}
