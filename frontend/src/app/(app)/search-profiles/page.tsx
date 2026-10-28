"use client";

import { Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Alert, Badge, Button, Card, Dialog, Empty, Field, Input, Select, Spinner, Switch } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { WORK_FORMAT_LABEL, dateTime } from "@/lib/format";
import type { Resume, SearchProfile } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const EXPERIENCE = { noExperience: "Без опыта", between1And3: "1–3 года", between3And6: "3–6 лет", moreThan6: "6+ лет" };
const TEMPLATES = {
  junior_developer: "Junior-разработчик",
  ai_automation: "AI / автоматизация",
  sysadmin: "Системный администратор",
  uxui_designer: "UX/UI-дизайнер",
  intern: "Стажёр",
  no_experience: "Без опыта",
};
const WEIGHT_LABEL = { skills: "Навыки", experience: "Опыт", title: "Должность", salary: "Зарплата", format_region: "Формат/регион", education_other: "Прочее" };
const DEFAULT_WEIGHTS = { skills: 30, experience: 20, title: 15, salary: 15, format_region: 10, education_other: 10 };

type Draft = Omit<SearchProfile, "id" | "last_run_at"> & { id?: string };

const EMPTY: Draft = {
  name: "",
  is_active: true,
  resume_id: null,
  positions: [],
  skills: [],
  areas: [{ id: "1", name: "Москва" }],
  work_formats: [],
  employment_types: [],
  experience: [],
  salary_min: null,
  currency: "RUR",
  only_with_salary: false,
  excluded_employers: [],
  excluded_keywords: [],
  period_days: 7,
  eligible_threshold: 70,
  review_threshold: 50,
  daily_apply_limit: 10,
  weights: DEFAULT_WEIGHTS,
  letter_template: "junior_developer",
  letter_tone: "neutral",
  letter_length: "short",
  letter_mode: "always",
  search_interval_minutes: 120,
};

const csv = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);

export default function SearchProfilesPage() {
  const { data, loading, reload } = useApi<SearchProfile[]>("/api/search-profiles");
  const { data: resumes } = useApi<Resume[]>("/api/resumes");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();

  const save = async () => {
    if (!draft) return;
    setBusy("save");
    try {
      const { id, ...body } = draft;
      if (id) await api.put(`/api/search-profiles/${id}`, body);
      else await api.post("/api/search-profiles", body);
      setDraft(null);
      reload();
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(null);
    }
  };

  const run = async (p: SearchProfile) => {
    setBusy(p.id);
    try {
      const r = await api.post<{ found: number; new: number; eligible: number }>(`/api/search-profiles/${p.id}/run`);
      toast(`Найдено ${r.found}, новых ${r.new}, подходят ${r.eligible}`, "ok");
      reload();
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(null);
    }
  };

  const remove = async (p: SearchProfile) => {
    if (!confirm(`Удалить профиль «${p.name}»?`)) return;
    await api.del(`/api/search-profiles/${p.id}`).catch((e) => toast(errorMessage(e), "bad"));
    reload();
  };

  return (
    <>
      <PageHeader
        title="Профили поиска"
        description="Отдельные наборы условий: например, «Python junior», «Стажировки», «AI-автоматизация»"
        actions={
          <Button onClick={() => setDraft({ ...EMPTY })}>
            <Plus className="size-4" /> Новый профиль
          </Button>
        }
      />
      <div className="mb-4">
        <Alert>
          Автоматический поиск работает через официальный API hh.ru и требует настроенного доступа. Без него профили всё равно
          нужны: по ним оцениваются вакансии, добавленные закладкой или вручную.
        </Alert>
      </div>
      {loading && !data ? (
        <Spinner />
      ) : !data || data.length === 0 ? (
        <Empty title="Профилей пока нет">Создайте первый профиль: должности, город, зарплата и пороги оценки.</Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.map((p) => (
            <Card key={p.id}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2 font-medium">
                    {p.name} {!p.is_active && <Badge>выключен</Badge>}
                  </div>
                  <div className="mt-1 text-sm text-muted">{p.positions.join(", ") || "должности не указаны"}</div>
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setDraft({ ...p })} aria-label="Изменить">
                    <Pencil className="size-4" />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => remove(p)} aria-label="Удалить">
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-1">
                {p.areas.map((a) => <Badge key={a.name}>{a.name}</Badge>)}
                {p.work_formats.map((f) => <Badge key={f}>{WORK_FORMAT_LABEL[f]}</Badge>)}
                {p.salary_min && <Badge>от {p.salary_min.toLocaleString("ru-RU")} ₽</Badge>}
                <Badge tone="brand">порог {p.eligible_threshold}</Badge>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-muted">
                <span>Последний поиск: {dateTime(p.last_run_at)}</span>
                <Button size="sm" variant="secondary" onClick={() => run(p)} loading={busy === p.id}>
                  <Play className="size-3.5" /> Искать сейчас
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={Boolean(draft)} onClose={() => setDraft(null)} title={draft?.id ? "Профиль поиска" : "Новый профиль поиска"} wide>
        {draft && (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Название">
                <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </Field>
              <Field label="Резюме">
                <Select value={draft.resume_id ?? ""} onChange={(e) => setDraft({ ...draft, resume_id: e.target.value || null })}>
                  <option value="">Лучшее подходящее</option>
                  {resumes?.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.title}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field label="Должности" hint="Через запятую">
              <Input defaultValue={draft.positions.join(", ")} onBlur={(e) => setDraft({ ...draft, positions: csv(e.target.value) })} />
            </Field>
            <Field label="Ключевые навыки" hint="Через запятую, используются если должности не заданы">
              <Input defaultValue={draft.skills.join(", ")} onBlur={(e) => setDraft({ ...draft, skills: csv(e.target.value) })} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Город" hint="ID региона hh.ru: 1 — Москва, 2 — Санкт-Петербург">
                <div className="flex gap-2">
                  <Input
                    className="w-20"
                    value={draft.areas[0]?.id ?? ""}
                    onChange={(e) => setDraft({ ...draft, areas: [{ id: e.target.value || null, name: draft.areas[0]?.name ?? "" }] })}
                  />
                  <Input
                    value={draft.areas[0]?.name ?? ""}
                    onChange={(e) => setDraft({ ...draft, areas: [{ id: draft.areas[0]?.id ?? null, name: e.target.value }] })}
                  />
                </div>
              </Field>
              <Field label="Зарплата от, ₽">
                <Input
                  type="number"
                  value={draft.salary_min ?? ""}
                  onChange={(e) => setDraft({ ...draft, salary_min: e.target.value ? Number(e.target.value) : null })}
                />
              </Field>
              <Field label="Откликов в день">
                <Input
                  type="number"
                  min={0}
                  max={50}
                  value={draft.daily_apply_limit}
                  onChange={(e) => setDraft({ ...draft, daily_apply_limit: Number(e.target.value) })}
                />
              </Field>
            </div>
            <div className="flex flex-wrap gap-4">
              {Object.entries(WORK_FORMAT_LABEL).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.work_formats.includes(k)}
                    onChange={(e) =>
                      setDraft({ ...draft, work_formats: e.target.checked ? [...draft.work_formats, k] : draft.work_formats.filter((x) => x !== k) })
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
            <div className="flex flex-wrap gap-4">
              {Object.entries(EXPERIENCE).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.experience.includes(k)}
                    onChange={(e) =>
                      setDraft({ ...draft, experience: e.target.checked ? [...draft.experience, k] : draft.experience.filter((x) => x !== k) })
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
            <Switch checked={draft.only_with_salary} onChange={(v) => setDraft({ ...draft, only_with_salary: v })} label="Только с указанной зарплатой" />
            <Field label="Исключить слова" hint="Вакансии с этими словами не подходят. Через запятую.">
              <Input defaultValue={draft.excluded_keywords.join(", ")} onBlur={(e) => setDraft({ ...draft, excluded_keywords: csv(e.target.value) })} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={`«Подходит» от ${draft.eligible_threshold}`}>
                <input type="range" min={0} max={100} value={draft.eligible_threshold} className="w-full" onChange={(e) => setDraft({ ...draft, eligible_threshold: Number(e.target.value) })} />
              </Field>
              <Field label={`«Проверить» от ${draft.review_threshold}`}>
                <input type="range" min={0} max={100} value={draft.review_threshold} className="w-full" onChange={(e) => setDraft({ ...draft, review_threshold: Number(e.target.value) })} />
              </Field>
            </div>
            <details className="rounded-lg border border-border p-3">
              <summary className="cursor-pointer text-sm font-medium">Веса оценки</summary>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                {Object.entries(WEIGHT_LABEL).map(([k, label]) => (
                  <Field key={k} label={label}>
                    <Input
                      type="number"
                      min={0}
                      value={draft.weights[k] ?? DEFAULT_WEIGHTS[k as keyof typeof DEFAULT_WEIGHTS]}
                      onChange={(e) => setDraft({ ...draft, weights: { ...DEFAULT_WEIGHTS, ...draft.weights, [k]: Number(e.target.value) } })}
                    />
                  </Field>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted">Веса нормализуются до 100.</p>
            </details>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Шаблон письма">
                <Select value={draft.letter_template} onChange={(e) => setDraft({ ...draft, letter_template: e.target.value })}>
                  {Object.entries(TEMPLATES).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Тон">
                <Select value={draft.letter_tone} onChange={(e) => setDraft({ ...draft, letter_tone: e.target.value })}>
                  <option value="formal">Официальный</option>
                  <option value="neutral">Нейтральный</option>
                  <option value="friendly">Дружелюбный</option>
                </Select>
              </Field>
              <Field label="Письмо">
                <Select value={draft.letter_mode} onChange={(e) => setDraft({ ...draft, letter_mode: e.target.value })}>
                  <option value="always">Всегда</option>
                  <option value="when_required">Только если требуется</option>
                  <option value="never">Не писать</option>
                </Select>
              </Field>
            </div>
            <Switch checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} label="Профиль активен" />
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setDraft(null)}>
                Отмена
              </Button>
              <Button onClick={save} loading={busy === "save"} disabled={!draft.name.trim()}>
                Сохранить
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
