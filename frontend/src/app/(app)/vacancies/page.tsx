"use client";

import { Bookmark, Plus } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { BookmarkletDialog, ImportDialog } from "@/components/import-dialog";
import { MatchCard } from "@/components/match-card";
import { Button, Empty, Input, Select, Spinner, Tabs } from "@/components/ui";
import type { Match } from "@/lib/types";
import { useApi } from "@/lib/use-api";

type Tab = "eligible" | "review" | "reject" | "applied" | "all";

function Inbox() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("decision") as Tab) || "eligible";
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("score");
  const [importOpen, setImportOpen] = useState(false);
  const [bookmarkOpen, setBookmarkOpen] = useState(false);

  const query = new URLSearchParams({ sort, per_page: "50" });
  if (tab === "eligible") ["eligible", "ready_to_apply"].forEach((d) => query.append("decision", d));
  else if (tab !== "all") query.append("decision", tab);
  if (q.trim()) query.set("q", q.trim());
  const { data, loading } = useApi<{ items: Match[]; total: number; counts: Record<string, number> }>(`/api/vacancies?${query}`);
  const c = data?.counts ?? {};

  return (
    <>
      <PageHeader
        title="Вакансии"
        description="Оценка каждой вакансии с объяснением: почему подходит и чего не хватает"
        actions={
          <>
            <Button variant="secondary" onClick={() => setBookmarkOpen(true)}>
              <Bookmark className="size-4" /> Закладка для hh.ru
            </Button>
            <Button onClick={() => setImportOpen(true)}>
              <Plus className="size-4" /> Добавить вакансию
            </Button>
          </>
        }
      />
      <Tabs
        value={tab}
        onChange={(v) => router.replace(`/vacancies?decision=${v}`)}
        items={[
          { value: "eligible", label: "Подходят", count: (c.eligible ?? 0) + (c.ready_to_apply ?? 0) },
          { value: "review", label: "Проверить", count: c.review ?? 0 },
          { value: "reject", label: "Не подходят", count: c.reject ?? 0 },
          { value: "applied", label: "С откликом", count: c.applied ?? 0 },
          { value: "all", label: "Все" },
        ]}
      />
      <div className="my-4 flex flex-wrap gap-2">
        <Input className="max-w-xs" placeholder="Поиск по названию или компании" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-48" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="score">По оценке</option>
          <option value="date">По дате</option>
          <option value="salary">По зарплате</option>
        </Select>
      </div>
      {loading && !data ? (
        <Spinner />
      ) : !data || data.items.length === 0 ? (
        <Empty title="Здесь пока пусто">
          Добавьте вакансию по ссылке или тексту, установите закладку для hh.ru или настройте профиль поиска.
        </Empty>
      ) : (
        <div className="space-y-3">
          {data.items.map((m) => (
            <MatchCard key={m.id} m={m} />
          ))}
          {data.total > data.items.length && (
            <p className="text-center text-sm text-muted">Показаны первые {data.items.length} из {data.total}</p>
          )}
        </div>
      )}
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <BookmarkletDialog open={bookmarkOpen} onClose={() => setBookmarkOpen(false)} />
    </>
  );
}

export default function VacanciesPage() {
  return (
    <Suspense>
      <Inbox />
    </Suspense>
  );
}
