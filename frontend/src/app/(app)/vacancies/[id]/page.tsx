"use client";

import { Ban, EyeOff, ExternalLink, RefreshCw, Send } from "lucide-react";
import { use, useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { ApplicationPanel } from "@/components/application-panel";
import { decisionTone } from "@/components/match-card";
import { Alert, Badge, Button, Card, CardTitle, SampleBadge, ScoreRing, Spinner } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { DECISION_LABEL, WORK_FORMAT_LABEL, money } from "@/lib/format";
import type { Application, Match } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const COMPONENT_LABEL: Record<string, string> = {
  skills: "Навыки",
  experience: "Опыт",
  title: "Должность",
  salary: "Зарплата",
  format_region: "Формат и регион",
  education_other: "Образование и прочее",
};

export default function VacancyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: m, loading, setData } = useApi<Match>(`/api/vacancies/${id}`);
  const [app, setApp] = useState<Application | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    if (m?.application) api.get<Application>(`/api/applications/${m.application.id}`).then(setApp).catch(() => {});
  }, [m?.application?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading && !m) return <Spinner />;
  if (!m) return <Alert tone="bad">Вакансия не найдена</Alert>;
  const v = m.vacancy;
  const a = m.analysis ?? {};

  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(null);
    }
  };
  const decide = (decision: string | null) =>
    act("decision", async () => setData({ ...m, ...(await api.post<Match>(`/api/vacancies/${m.id}/decision`, { decision })), analysis: m.analysis }));
  const prepare = () =>
    act("prepare", async () => {
      const created = await api.post<Application>(`/api/vacancies/${m.id}/prepare`);
      setApp(await api.get<Application>(`/api/applications/${created.id}`));
      setData({ ...m, application: { id: created.id, status: created.status } });
    });

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {v.title} {v.is_sample && <SampleBadge />}
          </span>
        }
        description={[v.employer_name, v.area_name, money(v.salary_from, v.salary_to, v.salary_currency)].filter(Boolean).join(" · ")}
        actions={
          v.url && (
            <a href={v.url} target="_blank" rel="noopener noreferrer">
              <Button variant="secondary">
                <ExternalLink className="size-4" /> На hh.ru
              </Button>
            </a>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Card>
            <div className="flex items-start gap-4">
              <ScoreRing score={m.score} />
              <div className="flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  {m.decision && <Badge tone={decisionTone(m.decision)}>{DECISION_LABEL[m.decision]}</Badge>}
                  {m.user_decision && m.ai_decision && m.user_decision !== m.ai_decision && (
                    <span className="text-xs text-muted">оценка системы: {DECISION_LABEL[m.ai_decision]}</span>
                  )}
                  {a.ai_adjustment !== undefined && <Badge tone="brand">AI {a.ai_adjustment > 0 ? "+" : ""}{a.ai_adjustment}</Badge>}
                </div>
                <p className="mt-2 text-sm">{m.reasoning_summary}</p>
              </div>
            </div>
            {a.components && (
              <div className="mt-5 space-y-2">
                {Object.entries(a.components as Record<string, number>).map(([k, val]) => (
                  <div key={k} className="flex items-center gap-3 text-sm">
                    <span className="w-44 shrink-0 text-muted">{COMPONENT_LABEL[k] ?? k}</span>
                    <div className="h-2 flex-1 rounded-full bg-bg">
                      <div className="h-2 rounded-full bg-brand" style={{ width: `${Math.round(val * 100)}%` }} />
                    </div>
                    <span className="w-16 text-right text-xs tabular-nums text-muted">вес {a.weights?.[k]}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <SkillList title="Совпадают" items={m.matched_skills} tone="ok" />
              <SkillList title="Не хватает" items={m.missing_skills} tone="neutral" />
            </div>
            {(a.hard_filter_failures?.length > 0 || m.risks.length > 0) && (
              <div className="mt-5 space-y-2">
                {(a.hard_filter_failures ?? []).map((f: string) => (
                  <Alert key={f} tone="bad">
                    {f}
                  </Alert>
                ))}
                {m.risks.map((r) => (
                  <Alert key={r} tone="warn">
                    {r}
                  </Alert>
                ))}
              </div>
            )}
            <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
              <span className="self-center text-sm text-muted">Ваше решение:</span>
              <Button size="sm" variant={m.user_decision === "eligible" ? "primary" : "secondary"} onClick={() => decide("eligible")} loading={busy === "decision"}>
                Подходит
              </Button>
              <Button size="sm" variant={m.user_decision === "review" ? "primary" : "secondary"} onClick={() => decide("review")}>
                Подумать
              </Button>
              <Button size="sm" variant={m.user_decision === "reject" ? "primary" : "secondary"} onClick={() => decide("reject")}>
                Не подходит
              </Button>
              {m.user_decision && (
                <Button size="sm" variant="ghost" onClick={() => decide(null)}>
                  Сбросить
                </Button>
              )}
            </div>
          </Card>

          <Card>
            <CardTitle>Описание</CardTitle>
            <div className="mb-3 flex flex-wrap gap-1">
              {v.work_formats.map((f) => (
                <Badge key={f}>{WORK_FORMAT_LABEL[f] ?? f}</Badge>
              ))}
              {v.has_test && <Badge tone="warn">нужен тест работодателя</Badge>}
              {v.response_letter_required && <Badge tone="warn">письмо обязательно</Badge>}
              {v.archived && <Badge tone="bad">в архиве</Badge>}
            </div>
            <div className="whitespace-pre-line text-sm leading-relaxed">{v.description_text}</div>
          </Card>
        </div>

        <div className="space-y-4">
          {app ? (
            <ApplicationPanel initial={app} />
          ) : (
            <Card>
              <CardTitle>Отклик</CardTitle>
              <p className="mb-4 text-sm text-muted">
                Подготовим сопроводительное письмо только из фактов вашего резюме. Перед отправкой его можно отредактировать.
              </p>
              <Button onClick={prepare} loading={busy === "prepare"} className="w-full" disabled={!m.recommended_resume_id}>
                <Send className="size-4" /> Подготовить отклик
              </Button>
              {!m.recommended_resume_id && <p className="mt-2 text-xs text-muted">Сначала загрузите резюме.</p>}
            </Card>
          )}
          <Card>
            <div className="flex flex-col gap-2">
              <Button variant="ghost" className="justify-start" onClick={() => act("re", async () => setData(await api.post<Match>(`/api/vacancies/${m.id}/reanalyze`)))} loading={busy === "re"}>
                <RefreshCw className="size-4" /> Переоценить
              </Button>
              <Button variant="ghost" className="justify-start" onClick={() => act("hide", async () => { await api.post(`/api/vacancies/${m.id}/hide`); toast("Вакансия скрыта", "ok"); })}>
                <EyeOff className="size-4" /> Скрыть
              </Button>
              {v.employer_name && (
                <Button variant="ghost" className="justify-start" onClick={() => act("ex", async () => { await api.post(`/api/vacancies/${m.id}/exclude-employer`); toast(`«${v.employer_name}» в стоп-листе`, "ok"); })}>
                  <Ban className="size-4" /> Не показывать эту компанию
                </Button>
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function SkillList({ title, items, tone }: { title: string; items: string[]; tone: "ok" | "neutral" }) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium">{title}</div>
      {items.length === 0 ? (
        <span className="text-sm text-muted">—</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {items.map((s) => (
            <Badge key={s} tone={tone}>
              {s}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
