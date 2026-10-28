"use client";

import { Check, Plus, Star, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Alert, Badge, Button, Card, CardTitle, Field, Input, Spinner, Textarea } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { VisibilitySummary } from "@/components/visibility";
import { api, errorMessage } from "@/lib/api";
import { date } from "@/lib/format";
import type { CandidateProfile, Resume } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const SOURCE_LABEL: Record<string, string> = { extracted: "из резюме", llm: "AI", user: "вы", hh: "hh.ru" };

export default function ResumePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const toast = useToast();
  const { data: resume, loading, reload } = useApi<Resume>(`/api/resumes/${id}`);
  const { data: versions } = useApi<Resume[]>(`/api/resumes/${id}/versions`);
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [newSkill, setNewSkill] = useState("");
  const [hhId, setHhId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (resume?.profile) setProfile(structuredClone(resume.profile));
    setHhId(resume?.hh_resume_id ?? "");
  }, [resume]);

  if (loading && !resume) return <Spinner />;
  if (!resume || !profile) return <Alert tone="bad">Резюме не найдено</Alert>;

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

  const save = (confirmAll: boolean) =>
    act("save", async () => {
      const r = await api.put<Resume>(`/api/resumes/${id}/profile`, { profile, confirm_all: confirmAll });
      toast(confirmAll ? "Профиль подтверждён" : "Сохранено как новая версия", "ok");
      router.replace(`/resumes/${r.id}`);
    });

  const v = resume.visibility;

  return (
    <>
      <PageHeader
        title={resume.title}
        description={`Версия ${resume.version} · ${profile.level !== "unknown" ? profile.level : "уровень не определён"} · опыт ${Math.floor(profile.total_experience_months / 12)} г. ${profile.total_experience_months % 12} мес.`}
        actions={
          <>
            {!resume.is_primary && (
              <Button variant="secondary" onClick={() => act("primary", async () => { await api.post(`/api/resumes/${id}/primary`); reload(); })}>
                <Star className="size-4" /> Сделать основным
              </Button>
            )}
            <Button variant="ghost" onClick={() => act("del", async () => { await api.del(`/api/resumes/${id}`); router.replace("/resumes"); })}>
              <Trash2 className="size-4" /> В архив
            </Button>
          </>
        }
      />

      {!resume.profile_confirmed && (
        <div className="mb-4">
          <Alert tone="warn" title="Проверьте, что всё распознано верно">
            Навыки и опыт извлечены автоматически. Удалите лишнее, добавьте недостающее и подтвердите профиль: письма и
            оценка вакансий опираются только на эти факты.
          </Alert>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <Card>
            <CardTitle>Навыки</CardTitle>
            <div className="flex flex-wrap gap-2">
              {profile.skills.map((s, i) => (
                <span key={`${s.name}-${i}`} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-sm">
                  {s.name}
                  <span className="text-xs text-muted">{s.confirmed ? "✓" : SOURCE_LABEL[s.source]}</span>
                  <button aria-label={`Удалить ${s.name}`} onClick={() => setProfile({ ...profile, skills: profile.skills.filter((_, j) => j !== i) })}>
                    <X className="size-3.5 text-muted" />
                  </button>
                </span>
              ))}
            </div>
            <form
              className="mt-3 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const name = newSkill.trim();
                if (!name) return;
                setProfile({ ...profile, skills: [...profile.skills, { name, years: null, source: "user", confirmed: true }] });
                setNewSkill("");
              }}
            >
              <Input className="max-w-xs" placeholder="Добавить навык" value={newSkill} onChange={(e) => setNewSkill(e.target.value)} />
              <Button type="submit" variant="secondary">
                <Plus className="size-4" />
              </Button>
            </form>
          </Card>

          <Card>
            <CardTitle>Желаемые должности</CardTitle>
            <Input
              value={profile.desired_positions.join(", ")}
              onChange={(e) => setProfile({ ...profile, desired_positions: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })}
            />
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="Минимальная зарплата, ₽">
                <Input
                  type="number"
                  value={profile.min_salary ?? ""}
                  onChange={(e) => setProfile({ ...profile, min_salary: e.target.value ? Number(e.target.value) : null })}
                />
              </Field>
            </div>
          </Card>

          <Card>
            <CardTitle>Опыт работы</CardTitle>
            {profile.experience.length === 0 && <p className="text-sm text-muted">Опыт не найден.</p>}
            <div className="space-y-4">
              {profile.experience.map((e, i) => (
                <div key={i} className="rounded-lg border border-border p-3">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Input value={e.title} onChange={(ev) => updateList(profile, setProfile, "experience", i, { title: ev.target.value })} placeholder="Должность" />
                    <Input value={e.company} onChange={(ev) => updateList(profile, setProfile, "experience", i, { company: ev.target.value })} placeholder="Компания" />
                  </div>
                  <div className="mt-1 text-xs text-muted">
                    {e.start ?? "?"} — {e.current ? "сейчас" : (e.end ?? "?")} · {SOURCE_LABEL[e.source]}
                  </div>
                  <Textarea
                    rows={3}
                    className="mt-2"
                    value={e.description}
                    onChange={(ev) => updateList(profile, setProfile, "experience", i, { description: ev.target.value })}
                  />
                </div>
              ))}
            </div>
          </Card>

          {profile.projects.length > 0 && (
            <Card>
              <CardTitle>Проекты</CardTitle>
              <ul className="space-y-2 text-sm">
                {profile.projects.map((p, i) => (
                  <li key={i}>
                    <span className="font-medium">{p.name}</span>
                    {p.technologies.length > 0 && <span className="text-muted"> · {p.technologies.join(", ")}</span>}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {profile.assumptions.length > 0 && (
            <Card>
              <CardTitle>Предположения (требуют проверки)</CardTitle>
              <ul className="space-y-1 text-sm">
                {profile.assumptions.map((a, i) => (
                  <li key={i}>
                    <span className="font-medium">{a.field}:</span> {a.value} <span className="text-muted">— {a.reason}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <div className="flex flex-wrap gap-2">
            <Button onClick={() => save(true)} loading={busy === "save"}>
              <Check className="size-4" /> Всё верно, подтвердить
            </Button>
            <Button variant="secondary" onClick={() => save(false)}>
              Сохранить изменения
            </Button>
          </div>
        </div>

        <div className="space-y-4">
          <Card>
            <CardTitle>Качество профиля: {resume.quality.score ?? 0}/100</CardTitle>
            {(resume.quality.recommendations ?? []).length === 0 ? (
              <p className="text-sm text-muted">Рекомендаций нет.</p>
            ) : (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {resume.quality.recommendations!.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardTitle>Связь с hh.ru</CardTitle>
            <Field label="ID резюме на hh.ru" hint="Из адреса резюме: hh.ru/resume/<id>. Нужен для откликов через API и напоминаний.">
              <div className="flex gap-2">
                <Input value={hhId} onChange={(e) => setHhId(e.target.value.trim())} />
                <Button
                  variant="secondary"
                  onClick={() => act("link", async () => { await api.post(`/api/resumes/${id}/link-hh`, { hh_resume_id: hhId }); toast("Сохранено", "ok"); reload(); })}
                  disabled={!hhId || hhId === resume.hh_resume_id}
                >
                  OK
                </Button>
              </div>
            </Field>
          </Card>

          {v && (
            <Card>
              <CardTitle>Поднятие в поиске</CardTitle>
              <VisibilitySummary v={v} />
              <div className="mt-4 flex flex-col gap-2">
                {v.mode === "api" ? (
                  <Button
                    disabled={v.cooldown_active}
                    loading={busy === "pub"}
                    onClick={() => act("pub", async () => { const r = await api.post<{ detail?: string }>(`/api/resumes/${id}/visibility/publish`); toast(r.detail ?? "Готово", "ok"); reload(); })}
                  >
                    Поднять через hh.ru
                  </Button>
                ) : (
                  <a href={v.manual_url} target="_blank" rel="noopener noreferrer">
                    <Button variant="secondary" className="w-full">
                      Открыть «Мои резюме» на hh.ru
                    </Button>
                  </a>
                )}
                <Button
                  variant="ghost"
                  onClick={() => act("mark", async () => { await api.post(`/api/resumes/${id}/visibility/mark-manual`); toast("Отмечено. Напомним, когда можно снова", "ok"); reload(); })}
                >
                  Я поднял(а) резюме на hh.ru
                </Button>
              </div>
              <p className="mt-3 text-xs text-muted">{v.paid_operations}</p>
            </Card>
          )}

          {versions && versions.length > 1 && (
            <Card>
              <CardTitle>Версии</CardTitle>
              <ul className="space-y-1 text-sm">
                {versions.map((r) => (
                  <li key={r.id} className="flex justify-between">
                    <span>
                      Версия {r.version} {r.id === resume.id && <Badge tone="brand">текущая</Badge>}
                    </span>
                    <span className="text-muted">{date(r.created_at)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function updateList<K extends "experience" | "education" | "projects">(
  profile: CandidateProfile,
  setProfile: (p: CandidateProfile) => void,
  key: K,
  index: number,
  patch: Partial<CandidateProfile[K][number]>,
) {
  const list = [...profile[key]] as CandidateProfile[K][number][];
  list[index] = { ...list[index], ...patch, source: "user", confirmed: true };
  setProfile({ ...profile, [key]: list });
}
