"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import { Alert, Button, Dialog, Field, Input, Textarea } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Match } from "@/lib/types";

export function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [form, setForm] = useState({ url: "", title: "", employer_name: "", salary_text: "", description: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const match = await api.post<Match>("/api/vacancies/import", { ...form, url: form.url || null, source: "manual" });
      onClose();
      router.push(`/vacancies/${match.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Добавить вакансию" wide>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Ссылка на вакансию hh.ru" hint="Если доступ к API hh.ru настроен, данные подтянутся сами. Иначе вставьте текст ниже.">
          <Input placeholder="https://hh.ru/vacancy/12345678" value={form.url} onChange={set("url")} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Должность">
            <Input value={form.title} onChange={set("title")} />
          </Field>
          <Field label="Компания">
            <Input value={form.employer_name} onChange={set("employer_name")} />
          </Field>
        </div>
        <Field label="Зарплата" hint="Как указано в вакансии, например «от 80 000 до 120 000 ₽»">
          <Input value={form.salary_text} onChange={set("salary_text")} />
        </Field>
        <Field label="Текст вакансии" hint="Скопируйте описание целиком: требования, задачи, условия">
          <Textarea rows={10} value={form.description} onChange={set("description")} />
        </Field>
        {error && <Alert tone="bad">{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={busy}>
            Оценить вакансию
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function BookmarkletDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [code, setCode] = useState<string | null>(null);
  useEffect(() => {
    if (!open || code !== null) return;
    api
      .get<{ code: string }>("/api/vacancies/bookmarklet")
      .then((r) => setCode(r.code))
      .catch(() => setCode(""));
  }, [open, code]);
  return (
    <Dialog open={open} onClose={onClose} title="Кнопка «В Ashore» для браузера">
      <ol className="list-decimal space-y-2 pl-5 text-sm">
        <li>Включите панель закладок в браузере (Ctrl+Shift+B или ⌘+Shift+B).</li>
        <li>Перетащите кнопку ниже на панель закладок.</li>
        <li>Откройте вакансию на hh.ru и нажмите закладку: вакансия откроется в Ashore на проверку.</li>
      </ol>
      <div className="my-5 flex justify-center">
        {code ? (
          <a
            onClick={(e) => e.preventDefault()}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-ink"
            ref={(el) => {
              // React blocks javascript: URLs in href; set it directly on the element for dragging.
              if (el && code) el.setAttribute("href", code);
            }}
          >
            В Ashore
          </a>
        ) : (
          <span className="text-sm text-muted">Загрузка…</span>
        )}
      </div>
      <Alert>
        Закладка читает только открытую вами страницу вакансии и передаёт текст в Ashore через адресную строку. Она не
        нажимает кнопки на hh.ru и не отправляет отклики.
      </Alert>
    </Dialog>
  );
}
