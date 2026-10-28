"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Alert, Button, Card, Field, Input, Textarea } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Match } from "@/lib/types";

interface Clip {
  url: string;
  title: string;
  employer_name: string;
  salary_text: string;
  description: string;
}

/** Receives a vacancy from the browser bookmarklet. Data arrives in the URL fragment and is shown before import. */
export default function ClipPage() {
  const router = useRouter();
  const [clip, setClip] = useState<Clip | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try {
      const raw = decodeURIComponent(window.location.hash.slice(1));
      const data = JSON.parse(raw);
      const str = (x: unknown, n: number) => (typeof x === "string" ? x.slice(0, n) : "");
      setClip({
        url: str(data.url, 500),
        title: str(data.title, 300),
        employer_name: str(data.employer_name, 300),
        salary_text: str(data.salary_text, 200),
        description: str(data.description, 60000),
      });
      history.replaceState(null, "", "/clip");
    } catch {
      setError("Не удалось прочитать данные вакансии. Откройте страницу вакансии на hh.ru и нажмите закладку ещё раз.");
    }
  }, []);

  const save = async () => {
    if (!clip) return;
    setBusy(true);
    try {
      const m = await api.post<Match>("/api/vacancies/import", { ...clip, source: "bookmarklet" });
      router.replace(`/vacancies/${m.id}`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Добавить вакансию из браузера" description="Проверьте, что данные считались верно" />
      {error && <Alert tone="bad">{error}</Alert>}
      {clip && (
        <Card className="space-y-4">
          <Field label="Должность">
            <Input value={clip.title} onChange={(e) => setClip({ ...clip, title: e.target.value })} />
          </Field>
          <Field label="Компания">
            <Input value={clip.employer_name} onChange={(e) => setClip({ ...clip, employer_name: e.target.value })} />
          </Field>
          <Field label="Зарплата">
            <Input value={clip.salary_text} onChange={(e) => setClip({ ...clip, salary_text: e.target.value })} />
          </Field>
          <Field label="Описание">
            <Textarea rows={12} value={clip.description} onChange={(e) => setClip({ ...clip, description: e.target.value })} />
          </Field>
          <div className="text-xs text-muted">{clip.url}</div>
          <Button onClick={save} loading={busy}>
            Добавить и оценить
          </Button>
        </Card>
      )}
    </>
  );
}
