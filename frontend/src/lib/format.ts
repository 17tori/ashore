export function money(from?: number | null, to?: number | null, currency?: string | null): string {
  const cur = currency === "RUR" || !currency ? "₽" : currency;
  const f = (n: number) => n.toLocaleString("ru-RU");
  if (from && to) return `${f(from)} – ${f(to)} ${cur}`;
  if (from) return `от ${f(from)} ${cur}`;
  if (to) return `до ${f(to)} ${cur}`;
  return "зарплата не указана";
}

export function dateTime(value?: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function date(value?: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
}

export function percent(value?: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

export const DECISION_LABEL: Record<string, string> = {
  reject: "Не подходит",
  review: "Проверить",
  eligible: "Подходит",
  ready_to_apply: "Готово к отклику",
  applied: "Отклик отправлен",
};

export const STATUS_LABEL: Record<string, string> = {
  found: "Найдена",
  analyzing: "Анализ",
  matched: "Подходит",
  awaiting_confirmation: "Ждёт подтверждения",
  ready: "В очереди",
  sending: "Отправляется",
  sent: "Отправлен",
  viewed: "Просмотрен",
  invitation: "Приглашение",
  rejected: "Отказ",
  archived: "В архиве",
  failed: "Ошибка",
  unknown: "Нужна проверка",
};

export const WORK_FORMAT_LABEL: Record<string, string> = {
  remote: "Удалённо",
  on_site: "В офисе",
  hybrid: "Гибрид",
  field_work: "Разъездная",
};

export const CAPABILITY_LABEL: Record<string, string> = {
  vacancy_search: "Поиск вакансий",
  resumes_read: "Чтение резюме",
  negotiations_read: "Статусы откликов",
  apply: "Отправка откликов",
  resume_publish: "Поднятие резюме",
};

export const CAPABILITY_STATUS_LABEL: Record<string, string> = {
  verified: "работает",
  conditional: "возможно",
  unavailable: "недоступно",
  unknown: "не проверено",
};
