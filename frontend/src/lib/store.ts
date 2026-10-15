"use client";

import { useCallback, useEffect, useState } from "react";
import { LessonSetup, ProficiencyLevel } from "./types";

const STORAGE_KEY = "socratic-tutor-setup";
const THEME_KEY = "socratic-tutor-theme";
const WEAK_LEXICON_KEY = "socratic-tutor-weak-lexicon";

export function generateClientId(): string {
  if (typeof window === "undefined") return "";
  let id = localStorage.getItem("socratic-tutor-client-id");
  if (!id) {
    id = `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
    localStorage.setItem("socratic-tutor-client-id", id);
  }
  return id;
}

export function saveSetup(setup: LessonSetup): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(setup));
}

export function loadSetup(): LessonSetup | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as LessonSetup;
    // Migrate old stored setup that may still contain selectedScenario.
    const { selectedScenario: _, ...cleaned } = parsed as LessonSetup & {
      selectedScenario?: string;
    };
    return cleaned;
  } catch {
    return null;
  }
}

export function clearSetup(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(STORAGE_KEY);
}

export function createDefaultSetup(): LessonSetup {
  return {
    clientId: generateClientId(),
    targetLanguage: "Spanish",
    homeLanguage: "English",
    proficiencyLevel: "A1",
    sessionLengthMinutes: 10,
    lockoutCooldownMinutes: 15,
    weakLexicon: [],
  };
}

/**
 * Persistent weak-lexicon / SRS bank.
 */
export function loadWeakLexicon(): string[] {
  if (typeof window === "undefined") return [];
  const raw = localStorage.getItem(WEAK_LEXICON_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((t) => typeof t === "string")) {
      return parsed;
    }
  } catch {
    // ignore
  }
  return [];
}

export function saveWeakLexicon(terms: string[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(WEAK_LEXICON_KEY, JSON.stringify(terms));
}

export function addWeakLexiconTerms(terms: string[]): string[] {
  const current = loadWeakLexicon();
  const next = Array.from(new Set([...current, ...terms])).slice(0, 50);
  saveWeakLexicon(next);
  return next;
}

export function clearWeakLexicon(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(WEAK_LEXICON_KEY);
}

export function loadTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function saveTheme(theme: "light" | "dark"): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(THEME_KEY, theme);
}

export function applyTheme(theme: "light" | "dark"): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

export function useSetup() {
  const [setup, setSetup] = useState<LessonSetup | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = loadSetup();
    const weakLexicon = loadWeakLexicon();
    setSetup(
      stored
        ? { ...createDefaultSetup(), ...stored, weakLexicon }
        : createDefaultSetup()
    );
    setHydrated(true);
  }, []);

  const updateSetup = useCallback(
    (patch: Partial<LessonSetup> | ((prev: LessonSetup) => LessonSetup)) => {
      setSetup((prev) => {
        const next =
          typeof patch === "function"
            ? patch(prev ?? createDefaultSetup())
            : { ...(prev ?? createDefaultSetup()), ...patch };
        saveSetup(next);
        return next;
      });
    },
    []
  );

  const resetSetup = useCallback(() => {
    clearSetup();
    setSetup(null);
  }, []);

  return {
    setup,
    hydrated,
    updateSetup,
    resetSetup,
    isComplete: Boolean(
      setup?.targetLanguage && setup?.homeLanguage && setup?.proficiencyLevel
    ),
  };
}

export function useTheme() {
  const [theme, setThemeState] = useState<"light" | "dark">("light");

  useEffect(() => {
    const initial = loadTheme();
    setThemeState(initial);
    applyTheme(initial);
  }, []);

  const setTheme = useCallback((next: "light" | "dark") => {
    setThemeState(next);
    saveTheme(next);
    applyTheme(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "light" ? "dark" : "light";
      saveTheme(next);
      applyTheme(next);
      return next;
    });
  }, []);

  return { theme, setTheme, toggleTheme };
}

export type { LessonSetup, ProficiencyLevel };
