"use client";

import Link from "next/link";
import { Badge, SampleBadge, ScoreRing } from "@/components/ui";
import { DECISION_LABEL, STATUS_LABEL, WORK_FORMAT_LABEL, dateTime, money } from "@/lib/format";
import type { Match } from "@/lib/types";

export function decisionTone(decision: string | null) {
  if (decision === "eligible" || decision === "ready_to_apply") return "ok" as const;
  if (decision === "review") return "warn" as const;
  if (decision === "applied") return "brand" as const;
  return "bad" as const;
}

export function MatchCard({ m }: { m: Match }) {
  const v = m.vacancy;
  return (
    <Link
      href={`/vacancies/${m.id}`}
      className="flex gap-4 rounded-xl border border-border bg-surface p-4 transition-colors hover:border-brand/40"
    >
      <ScoreRing score={m.score} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{v.title}</span>
          {v.is_sample && <SampleBadge />}
          {m.decision && <Badge tone={decisionTone(m.decision)}>{DECISION_LABEL[m.decision] ?? m.decision}</Badge>}
          {m.user_decision && <Badge>решение ваше</Badge>}
          {m.application && <Badge tone="brand">{STATUS_LABEL[m.application.status]}</Badge>}
        </div>
        <div className="mt-1 text-sm text-muted">
          {[v.employer_name, v.area_name, money(v.salary_from, v.salary_to, v.salary_currency)].filter(Boolean).join(" · ")}
          {v.work_formats.length > 0 && ` · ${v.work_formats.map((f) => WORK_FORMAT_LABEL[f] ?? f).join(", ")}`}
        </div>
        {m.reasoning_summary && <p className="mt-2 line-clamp-2 text-sm">{m.reasoning_summary}</p>}
        <div className="mt-2 flex flex-wrap gap-1">
          {m.matched_skills.slice(0, 6).map((s) => (
            <Badge key={s} tone="ok">
              {s}
            </Badge>
          ))}
          {m.missing_skills.slice(0, 4).map((s) => (
            <Badge key={s}>{s}</Badge>
          ))}
          {m.risks.slice(0, 2).map((r) => (
            <Badge key={r} tone="warn">
              {r}
            </Badge>
          ))}
        </div>
      </div>
      <div className="hidden shrink-0 text-right text-xs text-muted sm:block">{dateTime(v.published_at ?? m.discovered_at)}</div>
    </Link>
  );
}
