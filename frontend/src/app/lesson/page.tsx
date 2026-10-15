"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LessonRoom } from "@/components/LessonRoom";
import { LessonIntro } from "@/components/LessonIntro";
import { loadSetup, createDefaultSetup, useTheme } from "@/lib/store";
import { LessonSetup } from "@/lib/types";
import { Button, Card, CardDescription, CardHeader, CardTitle } from "@/components/ui";

export default function LessonPage() {
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();
  const [setup, setSetup] = useState<LessonSetup | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [showIntro, setShowIntro] = useState(true);

  useEffect(() => {
    const saved = loadSetup();
    setSetup(saved ?? createDefaultSetup());
    setHydrated(true);
  }, []);

  if (!hydrated) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4 bg-slate-50 dark:bg-slate-950">
        <p className="text-slate-500 dark:text-slate-400">Loading lesson…</p>
      </main>
    );
  }

  if (!setup) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4 bg-slate-50 dark:bg-slate-950">
        <Card className="max-w-md text-center dark:bg-slate-900 dark:border-slate-800">
          <CardHeader>
            <CardTitle>No lesson setup found</CardTitle>
            <CardDescription>
              Complete the onboarding wizard to configure your lesson.
            </CardDescription>
          </CardHeader>
          <Button onClick={() => router.push("/")}>Go to Setup</Button>
        </Card>
      </main>
    );
  }

  // Show intro screen first, then transition to lesson room
  if (showIntro) {
    return (
      <main className="min-h-screen bg-slate-50 dark:bg-slate-950">
        <div className="mx-auto max-w-3xl">
          <div className="mb-4 flex justify-end">
            <button
              type="button"
              onClick={toggleTheme}
              className="rounded-lg border border-slate-200 bg-white p-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
              aria-label="Toggle dark mode"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
          </div>
          <LessonIntro 
            setup={setup} 
            onComplete={() => setShowIntro(false)} 
          />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50 p-4 transition dark:bg-slate-950">
      <div className="mx-auto max-w-3xl">
        <div className="mb-4 flex justify-end">
          <button
            type="button"
            onClick={toggleTheme}
            className="rounded-lg border border-slate-200 bg-white p-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            aria-label="Toggle dark mode"
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
        </div>
        <LessonRoom setup={setup} />
      </div>
    </main>
  );
}
