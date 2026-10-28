"use client";

import { dateTime } from "@/lib/format";
import type { Visibility } from "@/lib/types";

export function VisibilitySummary({ v }: { v: Visibility }) {
  return (
    <div className="space-y-1.5 text-sm">
      <div className="flex justify-between">
        <span className="text-muted">Способ</span>
        <span>{v.mode === "api" ? "через API hh.ru" : "напоминания"}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted">Поднято (подтверждено hh.ru)</span>
        <span>{dateTime(v.last_platform_confirmed_at)}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted">Отмечено вами</span>
        <span>{dateTime(v.last_user_marked_at)}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted">Можно снова</span>
        <span>{v.cooldown_active ? dateTime(v.next_allowed_at) : "сейчас"}</span>
      </div>
    </div>
  );
}
