"use client";

import { Check, Copy, ExternalLink, RefreshCw, Send, SkipForward } from "lucide-react";
import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, CardTitle, Dialog, Select, Textarea } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { STATUS_LABEL, dateTime } from "@/lib/format";
import type { Application, ApproveResult } from "@/lib/types";

const EDITABLE = new Set(["matched", "awaiting_confirmation", "ready", "failed"]);
const SENT_LIKE = new Set(["sent", "viewed", "invitation", "rejected"]);

export function statusTone(status: string) {
  if (status === "invitation") return "ok" as const;
  if (status === "rejected" || status === "failed") return "bad" as const;
  if (status === "unknown" || status === "awaiting_confirmation") return "warn" as const;
  if (SENT_LIKE.has(status)) return "brand" as const;
  return "neutral" as const;
}

export function ApplicationPanel({ initial, onChange }: { initial: Application; onChange?: (a: Application) => void }) {
  const [app, setApp] = useState(initial);
  const [text, setText] = useState(initial.letter?.text ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<ApproveResult | null>(null);
  const [notes, setNotes] = useState(initial.notes);
  const toast = useToast();

  useEffect(() => {
    setApp(initial);
    setText(initial.letter?.text ?? "");
    setNotes(initial.notes);
  }, [initial]);

  const update = (a: Application) => {
    setApp(a);
    onChange?.(a);
  };

  const run = async <T,>(key: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(key);
    try {
      return await fn();
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(null);
    }
  };

  const editable = EDITABLE.has(app.status);
  const dirty = text !== (app.letter?.text ?? "");
  const issues = app.letter?.validation?.issues ?? [];

  const saveLetter = () =>
    run("save", async () => {
      const a = await api.put<Application>(`/api/applications/${app.id}/letter`, { text });
      update(a);
      toast(a.letter?.validation?.blocking ? "Сохранено, но письмо не прошло проверку" : "Письмо сохранено", a.letter?.validation?.blocking ? "bad" : "ok");
    });

  const regenerate = (useAi: boolean) =>
    run("regen", async () => {
      const a = await api.post<Application>(`/api/applications/${app.id}/letter/regenerate?use_ai=${useAi}`);
      update(a);
      setText(a.letter?.text ?? "");
    });

  const approve = () =>
    run("approve", async () => {
      if (dirty) {
        const saved = await api.put<Application>(`/api/applications/${app.id}/letter`, { text });
        update(saved);
        if (saved.letter?.validation?.blocking) {
          toast("Письмо не прошло проверку фактов", "bad");
          return;
        }
      }
      const r = await api.post<ApproveResult>(`/api/applications/${app.id}/approve`);
      update(r.application);
      if (r.mode === "manual") setHandoff(r);
      else toast(r.status === "sent" ? "hh.ru подтвердил отклик" : (r.detail ?? "Статус обновлён"), r.status === "sent" ? "ok" : "neutral");
    });

  const markSent = () =>
    run("sent", async () => {
      update(await api.post<Application>(`/api/applications/${app.id}/mark-sent`));
      setHandoff(null);
      toast("Отклик отмечен отправленным", "ok");
    });

  const notSent = () => run("notsent", async () => update(await api.post<Application>(`/api/applications/${app.id}/not-sent`)));
  const skip = () => run("skip", async () => update(await api.post<Application>(`/api/applications/${app.id}/skip`)));
  const setStatus = (status: string) =>
    run("status", async () => update(await api.post<Application>(`/api/applications/${app.id}/status`, { status })));
  const saveNotes = () => run("notes", async () => update(await api.put<Application>(`/api/applications/${app.id}/notes`, { notes })));

  return (
    <Card>
      <CardTitle action={<Badge tone={statusTone(app.status)}>{STATUS_LABEL[app.status] ?? app.status}</Badge>}>Отклик</CardTitle>

      {app.status === "unknown" && (
        <div className="mb-4">
          <Alert tone="warn" title="Неизвестно, дошёл ли отклик">
            hh.ru не ответил после отправки. Проверьте раздел «Отклики» на hh.ru и отметьте результат.
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={markSent} loading={busy === "sent"}>
                Отклик есть на hh.ru
              </Button>
              <Button size="sm" variant="secondary" onClick={notSent} loading={busy === "notsent"}>
                Отклика нет
              </Button>
            </div>
          </Alert>
        </div>
      )}

      {SENT_LIKE.has(app.status) && (
        <p className="mb-4 text-sm text-muted">
          Отправлен {dateTime(app.sent_at)} ·{" "}
          {app.confirmed_by === "platform" ? "подтверждено hh.ru" : "отмечено вами (hh.ru не подтверждал)"}
        </p>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Сопроводительное письмо</span>
          {app.letter && (
            <span className="text-xs text-muted">
              {app.letter.generator === "llm" ? "AI" : app.letter.generator === "user" ? "ваш текст" : "шаблон"} · {text.length} / 2000
            </span>
          )}
        </div>
        <Textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} disabled={!editable} />
        {issues.length > 0 && (
          <ul className="space-y-1 text-sm">
            {issues.map((i, n) => (
              <li key={n} className={i.severity === "error" ? "text-bad" : "text-warn"}>
                {i.severity === "error" ? "✕" : "!"} {i.message}
              </li>
            ))}
          </ul>
        )}
        {editable && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={saveLetter} disabled={!dirty} loading={busy === "save"}>
              Сохранить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => regenerate(false)} loading={busy === "regen"}>
              <RefreshCw className="size-4" /> Другой вариант
            </Button>
            <Button size="sm" variant="ghost" onClick={() => regenerate(true)} title="Нужны настроенный AI-провайдер и согласие в настройках">
              Улучшить с AI
            </Button>
          </div>
        )}
      </div>

      {editable && (
        <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
          <Button onClick={approve} loading={busy === "approve"}>
            <Send className="size-4" /> Откликнуться
          </Button>
          <Button variant="secondary" onClick={markSent} loading={busy === "sent"}>
            <Check className="size-4" /> Уже откликнулись на hh.ru
          </Button>
          <Button variant="ghost" onClick={skip} loading={busy === "skip"}>
            <SkipForward className="size-4" /> Пропустить
          </Button>
        </div>
      )}

      {SENT_LIKE.has(app.status) && (
        <div className="mt-5 flex items-center gap-2 border-t border-border pt-4">
          <span className="text-sm text-muted">Ответ работодателя:</span>
          <Select className="w-52" value="" onChange={(e) => e.target.value && setStatus(e.target.value)}>
            <option value="">Отметить…</option>
            {app.status === "sent" && <option value="viewed">Просмотрен</option>}
            {app.status !== "invitation" && app.status !== "rejected" && <option value="invitation">Приглашение</option>}
            {app.status !== "rejected" && <option value="rejected">Отказ</option>}
            <option value="archived">В архив</option>
          </Select>
        </div>
      )}

      <div className="mt-5 border-t border-border pt-4">
        <span className="text-sm font-medium">Заметки</span>
        <Textarea rows={3} className="mt-2" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Контакт рекрутера, дата интервью…" />
        {notes !== app.notes && (
          <Button size="sm" variant="secondary" className="mt-2" onClick={saveNotes} loading={busy === "notes"}>
            Сохранить заметку
          </Button>
        )}
      </div>

      {app.events && app.events.length > 0 && (
        <div className="mt-5 border-t border-border pt-4">
          <span className="text-sm font-medium">История</span>
          <ol className="mt-2 space-y-1 text-sm">
            {app.events.map((e, n) => (
              <li key={n} className="flex gap-2">
                <span className="w-28 shrink-0 text-muted">{dateTime(e.at)}</span>
                <span>
                  {STATUS_LABEL[e.to] ?? e.to}
                  {e.note && <span className="text-muted"> — {e.note}</span>}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <HandOff result={handoff} onClose={() => setHandoff(null)} onSent={markSent} busy={busy === "sent"} />
    </Card>
  );
}

function HandOff({ result, onClose, onSent, busy }: { result: ApproveResult | null; onClose: () => void; onSent: () => void; busy: boolean }) {
  const [copied, setCopied] = useState(false);
  if (!result) return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result.letter_text ?? "");
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Dialog open onClose={onClose} title="Отклик на сайте hh.ru">
      {result.reason && <p className="mb-4 text-sm text-muted">Через API отправить нельзя: {result.reason}.</p>}
      <ol className="space-y-4 text-sm">
        <li>
          <div className="mb-2 font-medium">1. Скопируйте письмо</div>
          <Button variant="secondary" onClick={copy} disabled={!result.letter_text}>
            {copied ? <Check className="size-4" /> : <Copy className="size-4" />} {copied ? "Скопировано" : "Скопировать письмо"}
          </Button>
        </li>
        <li>
          <div className="mb-2 font-medium">2. Откройте форму отклика и вставьте письмо</div>
          {result.apply_url ? (
            <a href={result.apply_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-brand">
              Открыть на hh.ru <ExternalLink className="size-4" />
            </a>
          ) : (
            <span className="text-muted">У этой вакансии нет ссылки на hh.ru (пример или ручной ввод без ссылки).</span>
          )}
        </li>
        <li>
          <div className="mb-2 font-medium">3. После отправки отметьте здесь</div>
          <Button onClick={onSent} loading={busy}>
            <Check className="size-4" /> Я отправил(а) отклик
          </Button>
        </li>
      </ol>
    </Dialog>
  );
}
