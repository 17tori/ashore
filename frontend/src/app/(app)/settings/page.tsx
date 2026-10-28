"use client";

import { Download, Link2, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Alert, Badge, Button, Card, CardTitle, Dialog, Field, Input, Spinner, Switch } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { CAPABILITY_LABEL, CAPABILITY_STATUS_LABEL, dateTime } from "@/lib/format";
import type { Capability, User } from "@/lib/types";
import { useApi } from "@/lib/use-api";

interface SettingsData {
  user: User;
  telegram: { configured: boolean; bot_username: string | null; linked: boolean; username: string | null; notifications_enabled: boolean };
  ai: { provider: string; external: boolean; consent: boolean; consent_at: string | null };
  pd_consent_at: string | null;
}

interface HhStatus {
  configured: boolean;
  app_token_configured: boolean;
  connection: { status: string; account_label: string; last_error: string | null; circuit_open_until: string | null; connected_at: string } | null;
  capabilities: Record<string, Capability>;
  redirect_uri: string;
}

const HH_RESULT: Record<string, { tone: "ok" | "bad"; text: string }> = {
  connected: { tone: "ok", text: "hh.ru подключён" },
  denied: { tone: "bad", text: "Доступ к hh.ru не выдан" },
  invalid_state: { tone: "bad", text: "Ссылка подключения устарела, попробуйте ещё раз" },
  exchange_failed: { tone: "bad", text: "hh.ru не выдал токен, попробуйте позже" },
};

function SettingsInner() {
  const { data, reload, setData } = useApi<SettingsData>("/api/settings");
  const { data: hh, reload: reloadHh } = useApi<HhStatus>("/api/hh/status");
  const [name, setName] = useState("");
  const [link, setLink] = useState<{ code: string; deep_link: string | null } | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    const r = params.get("hh");
    if (r && HH_RESULT[r]) {
      toast(HH_RESULT[r].text, HH_RESULT[r].tone);
      router.replace("/settings");
    }
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => setName(data?.user.display_name ?? ""), [data?.user.display_name]);

  if (!data) return <Spinner />;

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
  const patch = (body: Record<string, unknown>) => act("patch", async () => setData(await api.patch<SettingsData>("/api/settings", body)));

  return (
    <>
      <PageHeader title="Настройки" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Профиль</CardTitle>
          <div className="space-y-3">
            <Field label="Имя">
              <div className="flex gap-2">
                <Input value={name} onChange={(e) => setName(e.target.value)} />
                <Button variant="secondary" disabled={name === data.user.display_name} onClick={() => patch({ display_name: name })}>
                  OK
                </Button>
              </div>
            </Field>
            <div className="text-sm text-muted">
              {data.user.email} · часовой пояс {data.user.timezone}
            </div>
          </div>
        </Card>

        <Card>
          <CardTitle>hh.ru</CardTitle>
          {!hh ? (
            <Spinner />
          ) : !hh.configured ? (
            <div className="space-y-3 text-sm">
              <Alert title="Подключение через API не настроено">
                Для работы через API нужно приложение, зарегистрированное на dev.hh.ru, и ключи на сервере. Без этого всё
                работает в основном режиме: закладка или ручной импорт, отклик на сайте hh.ru в один клик, напоминания о
                поднятии резюме.
              </Alert>
              <p className="text-muted">Адрес возврата для регистрации приложения: <code className="text-xs">{hh.redirect_uri}</code></p>
            </div>
          ) : (
            <div className="space-y-3 text-sm">
              {hh.connection ? (
                <>
                  <div className="flex items-center justify-between">
                    <span>{hh.connection.account_label || "Аккаунт hh.ru"}</span>
                    <Badge tone={hh.connection.status === "active" ? "ok" : "bad"}>
                      {hh.connection.status === "active" ? "подключён" : "нужно переподключить"}
                    </Badge>
                  </div>
                  {hh.connection.circuit_open_until && (
                    <Alert tone="warn">Запросы приостановлены до {dateTime(hh.connection.circuit_open_until)}</Alert>
                  )}
                  <ul className="space-y-1.5">
                    {Object.entries(hh.capabilities).map(([k, c]) => (
                      <li key={k} className="flex justify-between gap-2">
                        <span title={c.detail}>{CAPABILITY_LABEL[k] ?? k}</span>
                        <Badge tone={c.status === "verified" ? "ok" : c.status === "unavailable" ? "bad" : "neutral"}>
                          {CAPABILITY_STATUS_LABEL[c.status]}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                  <p className="text-xs text-muted">
                    Отправка откликов и поднятие резюме отмечаются как «работает» только после первого успешного ответа hh.ru.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" onClick={() => act("probe", async () => { await api.post("/api/hh/probe"); reloadHh(); })} loading={busy === "probe"}>
                      Проверить доступ
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => act("import", async () => { const r = await api.post<{ imported: number }>("/api/hh/import-resumes"); toast(`Импортировано резюме: ${r.imported}`, "ok"); })}>
                      Импортировать резюме
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => act("dc", async () => { await api.del("/api/hh/connection"); reloadHh(); })}>
                      Отключить
                    </Button>
                  </div>
                </>
              ) : (
                <Button onClick={() => act("connect", async () => { const r = await api.post<{ authorize_url: string }>("/api/hh/connect"); window.location.href = r.authorize_url; })} loading={busy === "connect"}>
                  <Link2 className="size-4" /> Подключить hh.ru
                </Button>
              )}
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>AI</CardTitle>
          <div className="space-y-3 text-sm">
            <p className="text-muted">
              Сейчас используется: {data.ai.external ? `внешний провайдер (${data.ai.provider})` : "локальный анализ, без внешних сервисов"}.
            </p>
            <Switch
              checked={data.ai.consent}
              onChange={(v) => patch({ ai_external_consent: v })}
              label="Разрешаю передавать текст резюме и вакансий внешнему AI-провайдеру"
            />
            <p className="text-xs text-muted">
              Без этого согласия данные не покидают сервер Ashore. Согласие можно отозвать в любой момент.
              {data.ai.consent_at && ` Дано: ${dateTime(data.ai.consent_at)}.`}
            </p>
          </div>
        </Card>

        <Card>
          <CardTitle>Telegram</CardTitle>
          {!data.telegram.configured ? (
            <p className="text-sm text-muted">Бот не настроен на сервере.</p>
          ) : data.telegram.linked ? (
            <div className="space-y-3 text-sm">
              <p>Привязан{data.telegram.username && `: @${data.telegram.username}`}</p>
              <Switch
                checked={data.telegram.notifications_enabled}
                onChange={(v) => act("tg", async () => { await api.patch("/api/telegram/link", { notifications_enabled: v }); reload(); })}
                label="Присылать уведомления"
              />
              <Button size="sm" variant="ghost" onClick={() => act("unlink", async () => { await api.del("/api/telegram/link"); reload(); })}>
                Отвязать
              </Button>
            </div>
          ) : link ? (
            <div className="space-y-2 text-sm">
              {link.deep_link ? (
                <a href={link.deep_link} target="_blank" rel="noopener noreferrer" className="text-brand">
                  Открыть бота и привязать →
                </a>
              ) : (
                <p>
                  Отправьте боту: <code>/start {link.code}</code>
                </p>
              )}
              <p className="text-xs text-muted">Код действует 15 минут.</p>
              <Button size="sm" variant="secondary" onClick={() => { setLink(null); reload(); }}>
                Готово
              </Button>
            </div>
          ) : (
            <Button onClick={() => act("link", async () => setLink(await api.post("/api/telegram/link-code")))} loading={busy === "link"}>
              Привязать Telegram
            </Button>
          )}
          <p className="mt-3 text-xs text-muted">В Telegram приходят только уведомления и кнопки управления, без резюме и токенов.</p>
        </Card>

        <Card className="lg:col-span-2">
          <CardTitle>Мои данные</CardTitle>
          <p className="mb-3 text-sm text-muted">
            Согласие на обработку персональных данных дано {dateTime(data.pd_consent_at)}. Можно выгрузить всё, что хранится, или
            удалить аккаунт.
          </p>
          <div className="flex flex-wrap gap-2">
            <a href="/api/settings/export" download>
              <Button variant="secondary">
                <Download className="size-4" /> Выгрузить данные (JSON)
              </Button>
            </a>
            <Button variant="danger" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="size-4" /> Удалить аккаунт
            </Button>
          </div>
        </Card>
      </div>

      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} title="Удалить аккаунт">
        <div className="space-y-3 text-sm">
          <p>Будут безвозвратно удалены резюме, вакансии, отклики, письма, токены hh.ru и журнал. Отклики на самом hh.ru останутся.</p>
          <Field label="Пароль для подтверждения">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setDeleteOpen(false)}>
              Отмена
            </Button>
            <Button
              variant="danger"
              disabled={!password}
              loading={busy === "delete"}
              onClick={() => act("delete", async () => { await api.post("/api/settings/delete-account", { password }); window.location.href = "/register"; })}
            >
              Удалить навсегда
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}

export default function SettingsPage() {
  return (
    <Suspense>
      <SettingsInner />
    </Suspense>
  );
}
