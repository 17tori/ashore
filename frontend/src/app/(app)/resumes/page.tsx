"use client";

import clsx from "clsx";
import { Star, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Alert, Badge, Button, Card, CardTitle, Empty, Field, Input, Spinner, Switch, Textarea } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { date } from "@/lib/format";
import type { Resume } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function ResumesPage() {
  const { data, loading } = useApi<Resume[]>("/api/resumes");
  const router = useRouter();
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [paste, setPaste] = useState({ title: "", text: "" });
  const [useAi, setUseAi] = useState(false);

  const [dragging, setDragging] = useState(false);

  const upload = async (f: File | undefined) => {
    if (!f) return;
    const body = new FormData();
    body.append("file", f);
    body.append("use_ai", String(useAi));
    setBusy(true);
    try {
      const r = await api.post<Resume>("/api/resumes/upload", body);
      router.push(`/resumes/${r.id}`);
    } catch (e) {
      toast(errorMessage(e), "bad");
      setBusy(false);
      // Let the same file be picked again after a failed upload.
      if (file.current) file.current.value = "";
    }
  };

  const fromText = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post<Resume>(`/api/resumes/text?use_ai=${useAi}`, { title: paste.title || "Резюме", text: paste.text });
      router.push(`/resumes/${r.id}`);
    } catch (err) {
      toast(errorMessage(err), "bad");
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Резюме" description="Из резюме берутся только факты: навыки, опыт, проекты. Ничего не придумывается." />
      {loading && !data ? (
        <Spinner />
      ) : (
        <div className="space-y-6">
          {data && data.length > 0 && (
            <div className="grid gap-3 md:grid-cols-2">
              {data.map((r) => (
                <Link key={r.id} href={`/resumes/${r.id}`} className="rounded-xl border border-border bg-surface p-4 hover:border-brand/40">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{r.title}</span>
                    {r.is_primary && (
                      <Badge tone="brand">
                        <Star className="size-3" /> основное
                      </Badge>
                    )}
                    {!r.profile_confirmed && <Badge tone="warn">не проверено</Badge>}
                  </div>
                  <div className="mt-1 text-sm text-muted">
                    Версия {r.version} · навыков {r.skills_count} · {date(r.created_at)}
                    {r.hh_resume_id && " · связано с hh.ru"}
                  </div>
                  {r.quality?.score !== undefined && <div className="mt-2 text-sm">Качество профиля: {r.quality.score}/100</div>}
                </Link>
              ))}
            </div>
          )}
          {data && data.length === 0 && (
            <Empty title="Резюме ещё нет">Скачайте резюме с hh.ru в PDF или DOCX и загрузите сюда, или вставьте текст.</Empty>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardTitle>Загрузить файл</CardTitle>
              <p className="mb-3 text-sm text-muted">PDF, DOCX или TXT до 5 МБ. На hh.ru: «Мои резюме» → резюме → «Скачать».</p>
              <input
                ref={file}
                type="file"
                accept=".pdf,.docx,.txt"
                className="sr-only"
                tabIndex={-1}
                onChange={(e) => upload(e.target.files?.[0])}
              />
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  upload(e.dataTransfer.files[0]);
                }}
                className={clsx(
                  "mb-3 rounded-lg border-2 border-dashed p-4 text-center text-sm text-muted",
                  dragging ? "border-brand bg-brand/5" : "border-border",
                )}
              >
                Перетащите файл сюда или нажмите кнопку
              </div>
              <Button onClick={() => file.current?.click()} loading={busy}>
                <Upload className="size-4" /> Выбрать файл
              </Button>
            </Card>
            <Card>
              <CardTitle>Вставить текст</CardTitle>
              <form onSubmit={fromText} className="space-y-3">
                <Field label="Название">
                  <Input value={paste.title} onChange={(e) => setPaste({ ...paste, title: e.target.value })} placeholder="Например, Junior Python" />
                </Field>
                <Textarea rows={6} value={paste.text} onChange={(e) => setPaste({ ...paste, text: e.target.value })} placeholder="Текст резюме" />
                <Button type="submit" variant="secondary" loading={busy} disabled={paste.text.length < 20}>
                  Разобрать
                </Button>
              </form>
            </Card>
          </div>
          <Card>
            <Switch checked={useAi} onChange={setUseAi} label="Уточнить разбор с помощью AI" />
            <p className="mt-2 text-sm text-muted">
              Работает, только если на сервере настроен AI-провайдер и в настройках дано согласие на передачу данных. Иначе
              используется локальный разбор без внешних сервисов.
            </p>
          </Card>
          <Alert>
            Импорт резюме напрямую с hh.ru по API доступен только при подключённом приложении hh.ru. Без него файл из hh.ru
            даёт тот же результат.
          </Alert>
        </div>
      )}
    </>
  );
}
