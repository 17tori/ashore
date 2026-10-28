"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/app-shell";
import { Alert, Card, CardTitle, Spinner, Stat, Tabs } from "@/components/ui";
import { percent } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { useApi } from "@/lib/use-api";

type Period = "day" | "week" | "month";
type Row = { key: string; sent: number; invitations: number };

interface Report {
  overview: Overview;
  series: { bucket: string; found: number; suitable: number; sent: number; invitations: number }[];
  breakdowns: Record<"companies" | "positions" | "resumes" | "letters" | "channels", Row[]> & {
    api_errors: { operation: string; error: string; count: number }[];
  };
}

const SERIES = [
  { key: "found", name: "Найдено", color: "var(--series-1)" },
  { key: "suitable", name: "Подходит", color: "var(--series-2)" },
  { key: "sent", name: "Отклики", color: "var(--series-3)" },
  { key: "invitations", name: "Приглашения", color: "var(--series-4)" },
];

const LETTER_LABEL: Record<string, string> = {
  junior_developer: "Junior-разработчик",
  ai_automation: "AI / автоматизация",
  sysadmin: "Сисадмин",
  uxui_designer: "UX/UI",
  intern: "Стажёр",
  no_experience: "Без опыта",
  custom: "Своё письмо",
  local: "шаблон",
  llm: "AI",
  user: "вручную",
};
const letterKey = (k: string) => k.split(" · ").map((p) => LETTER_LABEL[p] ?? p).join(" · ");

const axis = { stroke: "var(--color-muted)", fontSize: 12, tickLine: false, axisLine: false };
const tooltipStyle = {
  contentStyle: { background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "var(--color-ink)" },
};

export default function AnalyticsPage() {
  const [period, setPeriod] = useState<Period>("week");
  const { data, loading } = useApi<Report>(`/api/analytics?period=${period}`);
  const o = data?.overview;
  const label = (b: string) =>
    new Date(b).toLocaleDateString("ru-RU", period === "month" ? { month: "short", year: "2-digit" } : { day: "numeric", month: "short" });

  return (
    <>
      <PageHeader title="Аналитика" description="Только факты из базы: ничего не оценивается за hh.ru" />
      <Tabs
        value={period}
        onChange={setPeriod}
        items={[
          { value: "day", label: "По дням (30 дней)" },
          { value: "week", label: "По неделям (полгода)" },
          { value: "month", label: "По месяцам (год)" },
        ]}
      />
      {loading && !data ? (
        <Spinner />
      ) : !data || !o ? (
        <Alert tone="bad">Не удалось загрузить</Alert>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Найдено" value={o.found} hint={`подходит ${percent(o.suitable_rate)}`} />
            <Stat label="Откликов" value={o.sent} hint={`подтверждено hh.ru: ${o.sent_platform_confirmed}`} />
            <Stat label="Приглашений" value={o.invitations} hint={`конверсия ${percent(o.invitation_rate)}`} />
            <Stat label="Средняя оценка откликов" value={o.avg_sent_score ?? "—"} hint={`дубликатов отсеяно: ${o.duplicates}`} />
          </div>

          <Card>
            <CardTitle>Воронка во времени</CardTitle>
            {data.series.length === 0 ? (
              <p className="text-sm text-muted">Данных пока нет.</p>
            ) : (
              <div className="h-72">
                <ResponsiveContainer>
                  <LineChart data={data.series} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                    <CartesianGrid stroke="var(--color-border)" vertical={false} />
                    <XAxis dataKey="bucket" tickFormatter={label} {...axis} />
                    <YAxis allowDecimals={false} {...axis} />
                    <Tooltip labelFormatter={(b) => label(String(b))} {...tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {SERIES.map((s) => (
                      <Line key={s.key} dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 5 }} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <BreakdownChart title="Компании" rows={data.breakdowns.companies} />
            <BreakdownChart title="Должности" rows={data.breakdowns.positions} />
            <BreakdownChart title="Резюме" rows={data.breakdowns.resumes} />
            <BreakdownChart title="Шаблоны писем" rows={data.breakdowns.letters.map((r) => ({ ...r, key: letterKey(r.key) }))} />
          </div>

          <Card>
            <CardTitle>Интеграция и расходы</CardTitle>
            <div className="grid gap-3 text-sm sm:grid-cols-4">
              <div>Запросов к hh.ru: {o.api_calls}</div>
              <div>Ошибок: {o.api_errors}</div>
              <div>AI: {o.ai_cost.toFixed(2)} $</div>
              <div>Платные услуги hh.ru: {o.paid_hh_cost.toFixed(0)} ₽</div>
            </div>
            {data.breakdowns.api_errors.length > 0 && (
              <table className="mt-4 w-full text-sm">
                <tbody>
                  {data.breakdowns.api_errors.map((e) => (
                    <tr key={`${e.operation}-${e.error}`} className="border-t border-border">
                      <td className="py-1.5">{e.operation}</td>
                      <td className="py-1.5 font-mono text-xs">{e.error}</td>
                      <td className="py-1.5 text-right tabular-nums">{e.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
    </>
  );
}

function BreakdownChart({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">Пока нет отправленных откликов.</p>
      ) : (
        <div style={{ height: Math.max(120, rows.length * 36 + 40) }}>
          <ResponsiveContainer>
            <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 0 }} barGap={2}>
              <CartesianGrid stroke="var(--color-border)" horizontal={false} />
              <XAxis type="number" allowDecimals={false} {...axis} />
              <YAxis
                type="category"
                dataKey="key"
                width={150}
                tickFormatter={(k: string) => (k.length > 22 ? `${k.slice(0, 21)}…` : k)}
                {...axis}
              />
              <Tooltip cursor={{ fill: "var(--color-bg)" }} {...tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="sent" name="Отклики" fill="var(--series-1)" radius={[0, 4, 4, 0]} barSize={10} />
              <Bar dataKey="invitations" name="Приглашения" fill="var(--series-2)" radius={[0, 4, 4, 0]} barSize={10} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
