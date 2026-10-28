import type { ReactNode } from "react";

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center text-2xl font-semibold">
          Ashore<span className="text-brand">.</span>
        </div>
        {children}
      </div>
    </div>
  );
}
