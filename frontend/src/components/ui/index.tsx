"use client";

import clsx from "clsx";
import { X } from "lucide-react";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  useEffect,
} from "react";

export { clsx as cn };

type Variant = "primary" | "secondary" | "ghost" | "danger";

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }
>(function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...props }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-brand text-brand-ink hover:opacity-90",
        variant === "secondary" && "border border-border bg-surface hover:bg-bg",
        variant === "ghost" && "hover:bg-bg",
        variant === "danger" && "bg-bad text-white hover:opacity-90",
        className,
      )}
      {...props}
    >
      {loading && <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
});

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-xl border border-border bg-surface p-5", className)}>{children}</div>;
}

export function CardTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h2 className="text-base font-semibold">{children}</h2>
      {action}
    </div>
  );
}

type Tone = "neutral" | "ok" | "warn" | "bad" | "brand";

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium",
        tone === "neutral" && "bg-bg text-muted ring-1 ring-border",
        tone === "ok" && "bg-ok/10 text-ok",
        tone === "warn" && "bg-warn/10 text-warn",
        tone === "bad" && "bg-bad/10 text-bad",
        tone === "brand" && "bg-brand/10 text-brand",
      )}
    >
      {children}
    </span>
  );
}

export function SampleBadge() {
  return (
    <Badge tone="warn" title="Демонстрационные данные, не настоящая вакансия">
      Пример
    </Badge>
  );
}

const field = "w-full rounded-lg border border-border bg-surface px-3 text-sm placeholder:text-muted";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={clsx(field, "h-10", className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return <textarea ref={ref} className={clsx(field, "py-2 leading-relaxed", className)} {...props} />;
  },
);

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx(field, "h-10", className)} {...props}>
      {children}
    </select>
  );
}

export function Label({ children, hint, htmlFor }: { children: ReactNode; hint?: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-sm font-medium">
      {children}
      {hint && <span className="mt-0.5 block text-xs font-normal text-muted">{hint}</span>}
    </label>
  );
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <Label hint={hint}>{label}</Label>
      {children}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={clsx("flex cursor-pointer items-center gap-3 text-sm", disabled && "opacity-50")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          "relative h-6 w-10 shrink-0 rounded-full transition-colors",
          checked ? "bg-brand" : "bg-border",
        )}
      >
        <span
          className={clsx(
            "absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-4.5" : "translate-x-0.5",
          )}
        />
      </button>
      <span>{label}</span>
    </label>
  );
}

export function Alert({ tone = "neutral", title, children }: { tone?: Tone; title?: ReactNode; children?: ReactNode }) {
  return (
    <div
      role={tone === "bad" ? "alert" : "status"}
      className={clsx(
        "rounded-lg border px-4 py-3 text-sm",
        tone === "neutral" && "border-border bg-bg",
        tone === "ok" && "border-ok/30 bg-ok/5",
        tone === "warn" && "border-warn/30 bg-warn/5",
        tone === "bad" && "border-bad/30 bg-bad/5",
        tone === "brand" && "border-brand/30 bg-brand/5",
      )}
    >
      {title && <div className="font-medium">{title}</div>}
      {children && <div className={clsx(title && "mt-1", "text-muted")}>{children}</div>}
    </div>
  );
}

export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        className={clsx("w-full rounded-xl border border-border bg-surface p-5 shadow-xl", wide ? "max-w-3xl" : "max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Закрыть" className="rounded p-1 text-muted hover:bg-bg">
            <X className="size-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T;
  onChange: (v: T) => void;
  items: { value: T; label: ReactNode; count?: number }[];
}) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-border">
      {items.map((item) => (
        <button
          key={item.value}
          onClick={() => onChange(item.value)}
          className={clsx(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
            value === item.value ? "border-brand font-medium text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {item.label}
          {item.count !== undefined && <span className="ml-1.5 text-xs text-muted">{item.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Empty({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border px-6 py-12 text-center">
      <div className="font-medium">{title}</div>
      {children && <div className="mx-auto mt-2 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <span className="size-6 animate-spin rounded-full border-2 border-brand border-t-transparent" />
    </div>
  );
}

export function ScoreRing({ score }: { score: number | null }) {
  const value = score ?? 0;
  const tone = score == null ? "text-muted" : value >= 70 ? "text-ok" : value >= 50 ? "text-warn" : "text-bad";
  return (
    <div className={clsx("relative grid size-12 shrink-0 place-items-center", tone)} aria-label={`Оценка ${score ?? "нет"}`}>
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
        <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth="3" />
        <circle
          cx="18"
          cy="18"
          r="15.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeDasharray={`${(value / 100) * 97.4} 97.4`}
          strokeLinecap="round"
        />
      </svg>
      <span className="text-sm font-semibold tabular-nums">{score ?? "—"}</span>
    </div>
  );
}

export function Stat({ label, value, hint }: { label: ReactNode; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}
