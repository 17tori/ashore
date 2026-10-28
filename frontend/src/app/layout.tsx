import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ToastProvider } from "@/components/ui/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ashore Careers — поиск работы на hh.ru",
  description: "Персональный помощник для поиска работы: анализ вакансий, письма, отклики и аналитика.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
