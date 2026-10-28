"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "", display_name: "" });
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!consent) {
      setError("Нужно согласие на обработку персональных данных");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Moscow";
      await api.post("/api/auth/register", { ...form, pd_consent: true, timezone });
      router.replace("/resumes?welcome=1");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <h1 className="mb-4 text-lg font-semibold">Регистрация</h1>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Имя" hint="Необязательно, только для обращения в интерфейсе">
          <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </Field>
        <Field label="Email">
          <Input type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Пароль" hint="Не короче 10 символов">
          <Input
            type="password"
            autoComplete="new-password"
            minLength={10}
            required
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            Даю согласие на обработку персональных данных в соответствии с{" "}
            <Link href="/privacy" target="_blank" className="text-brand">
              политикой конфиденциальности
            </Link>{" "}
            (152-ФЗ). Данные резюме не передаются внешним AI-сервисам без отдельного согласия.
          </span>
        </label>
        {error && <Alert tone="bad">{error}</Alert>}
        <Button type="submit" loading={busy} className="w-full">
          Создать аккаунт
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-muted">
        Уже есть аккаунт?{" "}
        <Link href="/login" className="text-brand">
          Войти
        </Link>
      </p>
    </Card>
  );
}
