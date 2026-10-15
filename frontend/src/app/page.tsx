"use client";

import { useRouter } from "next/navigation";
import { OnboardingWizard } from "@/components/OnboardingWizard";
import { useSetup, createDefaultSetup, useTheme } from "@/lib/store";
import { LessonSetup } from "@/lib/types";

export default function HomePage() {
  const router = useRouter();
  const { setup, hydrated } = useSetup();
  const { theme, toggleTheme } = useTheme();

  const handleComplete = (nextSetup: LessonSetup) => {
    router.push("/lesson");
  };

  if (!hydrated) {
    return (
      <main className="flex min-h-screen items-center justify-center p-6 bg-slate-50 dark:bg-slate-950">
        <p className="text-slate-500 dark:text-slate-400">Loading setup…</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-6 transition dark:bg-slate-950">
      <div className="mb-8 text-center">
        <h1 className="mb-2 text-3xl font-bold text-slate-900 dark:text-white">
          Audio-First Socratic Tutor
        </h1>
        <p className="text-slate-600 dark:text-slate-400">
          Configure your lesson, then speak with Coach Alex.
        </p>
      </div>
      <OnboardingWizard
        initialSetup={setup ?? createDefaultSetup()}
        onComplete={handleComplete}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
    </main>
  );
}
