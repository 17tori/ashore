"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { ApplicationPanel, statusTone } from "@/components/application-panel";
import { Badge, Dialog, Empty, SampleBadge, Spinner, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { STATUS_LABEL, dateTime, money } from "@/lib/format";
import type { Application } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const GROUPS: Record<string, string[]> = {
  awaiting_confirmation: ["awaiting_confirmation", "matched", "ready", "failed"],
  unknown: ["unknown", "sending"],
  sent: ["sent", "viewed"],
  invitation: ["invitation"],
  rejected: ["rejected"],
  archived: ["archived"],
};

function Crm() {
  const params = useSearchParams();
  const router = useRouter();
  const group = params.get("status") ?? "awaiting_confirmation";
  const query = new URLSearchParams({ per_page: "100" });
  (GROUPS[group] ?? []).forEach((s) => query.append("status", s));
  const { data, loading, reload } = useApi<{ items: Application[]; total: number; counts: Record<string, number> }>(
    `/api/applications?${query}`,
  );
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Application | null>(null);

  useEffect(() => {
    setDetail(null);
    if (openId) api.get<Application>(`/api/applications/${openId}`).then(setDetail).catch(() => setOpenId(null));
  }, [openId]);

  const count = (g: string) => (GROUPS[g] ?? []).reduce((n, s) => n + (data?.counts[s] ?? 0), 0);

  return (
    <>
      <PageHeader title="Отклики" description="Вся история: что отправлено, кем подтверждено и что ответил работодатель" />
      <Tabs
        value={group}
        onChange={(v) => router.replace(`/applications?status=${v}`)}
        items={[
          { value: "awaiting_confirmation", label: "Ждут решения", count: count("awaiting_confirmation") },
          { value: "unknown", label: "Проверить", count: count("unknown") },
          { value: "sent", label: "Отправлены", count: count("sent") },
          { value: "invitation", label: "Приглашения", count: count("invitation") },
          { value: "rejected", label: "Отказы", count: count("rejected") },
          { value: "archived", label: "Архив", count: count("archived") },
        ]}
      />
      <div className="mt-4">
        {loading && !data ? (
          <Spinner />
        ) : !data || data.items.length === 0 ? (
          <Empty title="Здесь пусто">Подготовьте отклик из карточки вакансии.</Empty>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border bg-surface">
            <table className="w-full text-sm">
              <thead className="border-b border-border text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Вакансия</th>
                  <th className="px-4 py-2 font-medium">Статус</th>
                  <th className="px-4 py-2 font-medium">Канал</th>
                  <th className="px-4 py-2 font-medium">Обновлён</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id} className="cursor-pointer border-b border-border last:border-0 hover:bg-bg" onClick={() => setOpenId(a.id)}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 font-medium">
                        {a.vacancy.title} {a.vacancy.is_sample && <SampleBadge />}
                      </div>
                      <div className="text-xs text-muted">
                        {a.vacancy.employer_name} · {money(a.vacancy.salary_from, a.vacancy.salary_to, a.vacancy.salary_currency)}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={statusTone(a.status)}>{STATUS_LABEL[a.status] ?? a.status}</Badge>
                    </td>
                    <td className="px-4 py-3 text-muted">
                      {a.channel === "api" ? "API hh.ru" : a.channel === "manual" ? "на сайте" : "—"}
                      {a.confirmed_by && <div className="text-xs">{a.confirmed_by === "platform" ? "подтвердил hh.ru" : "отметили вы"}</div>}
                    </td>
                    <td className="px-4 py-3 text-muted">{dateTime(a.status_changed_at ?? a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Dialog open={Boolean(openId)} onClose={() => { setOpenId(null); reload(); }} title={detail?.vacancy.title ?? "Отклик"} wide>
        {detail ? <ApplicationPanel initial={detail} /> : <Spinner />}
      </Dialog>
    </>
  );
}

export default function ApplicationsPage() {
  return (
    <Suspense>
      <Crm />
    </Suspense>
  );
}
