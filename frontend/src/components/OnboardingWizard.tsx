"use client";

import { useState } from "react";
import { Button, Card, CardDescription, CardHeader, CardTitle, RadioGroup } from "@/components/ui";
import { LessonSetup, ProficiencyLevel } from "@/lib/types";

const LANGUAGES = [
  { value: "Spanish", label: "Spanish", description: "Learn Spanish through spoken practice" },
  { value: "German", label: "German", description: "Learn German through spoken practice" },
  { value: "French", label: "French", description: "Learn French through spoken practice" },
  { value: "Japanese", label: "Japanese", description: "Learn Japanese through spoken practice" },
  { value: "Mandarin", label: "Mandarin", description: "Learn Mandarin through spoken practice" },
];

const HOME_LANGUAGES = [
  { value: "English", label: "English" },
  { value: "Spanish", label: "Spanish" },
  { value: "German", label: "German" },
  { value: "French", label: "French" },
  { value: "Portuguese", label: "Portuguese" },
  { value: "Italian", label: "Italian" },
];

const LEVELS: { value: ProficiencyLevel; label: string; description: string }[] = [
  { value: "A1", label: "A1 — Absolute Beginner", description: "Can use simple phrases and sentences" },
  { value: "A2", label: "A2 — Elementary", description: "Can communicate in routine situations" },
  { value: "B1", label: "B1 — Intermediate", description: "Can deal with most travel situations" },
  { value: "B2", label: "B2 — Upper Intermediate", description: "Can interact with fluency and spontaneity" },
  { value: "C1", label: "C1 — Advanced", description: "Can express ideas fluently and flexibly" },
];

interface OnboardingWizardProps {
  initialSetup: LessonSetup;
  onComplete: (setup: LessonSetup) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export function OnboardingWizard({
  initialSetup,
  onComplete,
  theme,
  onToggleTheme,
}: OnboardingWizardProps) {
  const [step, setStep] = useState(0);
  const [setup, setSetup] = useState<LessonSetup>(initialSetup);

  const totalSteps = 4;

  const update = (patch: Partial<LessonSetup>) =>
    setSetup((prev) => ({ ...prev, ...patch }));

  const steps = [
    {
      title: "Choose your target language",
      description: "You will practice speaking this language throughout the session.",
      content: (
        <RadioGroup
          name="targetLanguage"
          value={setup.targetLanguage}
          options={LANGUAGES.map((lang) => ({
            ...lang,
            disabled: lang.value === setup.homeLanguage,
          }))}
          onChange={(value) => update({ targetLanguage: value })}
        />
      ),
    },
    {
      title: "Choose your home language",
      description: "This is your native or strongest language. Used only for A1/A2 safety hints.",
      content: (
        <RadioGroup
          name="homeLanguage"
          value={setup.homeLanguage}
          options={HOME_LANGUAGES.map((lang) => ({
            ...lang,
            disabled: lang.value === setup.targetLanguage,
          }))}
          onChange={(value) => update({ homeLanguage: value })}
        />
      ),
    },
    {
      title: "What is your proficiency level?",
      description: "This determines how much scaffolding Coach Alex will provide.",
      content: (
        <RadioGroup
          name="proficiency"
          value={setup.proficiencyLevel}
          options={LEVELS.map((level) => ({
            value: level.value,
            label: level.label,
            description: level.description,
          }))}
          onChange={(value) => update({ proficiencyLevel: value as ProficiencyLevel })}
        />
      ),
    },
    {
      title: "Lesson setup",
      description: "Pick a session length and lockout cooldown.",
      content: (
        <div className="space-y-6">
          <div>
            <label className="mb-2 block text-sm font-semibold text-slate-700 dark:text-slate-300">
              Session length
            </label>
            <RadioGroup
              name="sessionLength"
              value={String(setup.sessionLengthMinutes)}
              options={[
                { value: "10", label: "10 minutes — Quick sprint" },
                { value: "20", label: "20 minutes — Standard lesson" },
                { value: "30", label: "30 minutes — Deep practice" },
              ]}
              onChange={(value) => update({ sessionLengthMinutes: Number(value) })}
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-semibold text-slate-700 dark:text-slate-300">
              Lockout cooldown: {setup.lockoutCooldownMinutes} minutes
            </label>
            <input
              type="range"
              min={5}
              max={60}
              step={5}
              value={setup.lockoutCooldownMinutes}
              onChange={(e) =>
                update({ lockoutCooldownMinutes: Number(e.target.value) })
              }
              className="w-full accent-tutor-700"
            />
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Time before you can start a new lesson after receiving 5 drift strikes.
            </p>
          </div>
        </div>
      ),
    },
  ];

  const current = steps[step];

  return (
    <Card className="mx-auto w-full max-w-2xl dark:bg-slate-900 dark:border-slate-800">
      <CardHeader>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Step {step + 1} of {totalSteps}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onToggleTheme}
              className="rounded-lg border border-slate-200 bg-white p-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              aria-label="Toggle dark mode"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <span className="text-xs text-slate-400 dark:text-slate-500">
              {Math.round(((step + 1) / totalSteps) * 100)}%
            </span>
          </div>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div
            className="h-full rounded-full bg-tutor-500 transition-all"
            style={{ width: `${((step + 1) / totalSteps) * 100}%` }}
          />
        </div>
        <CardTitle className="mt-4 dark:text-white">{current.title}</CardTitle>
        <CardDescription>{current.description}</CardDescription>
      </CardHeader>

      <div className="mb-6">{current.content}</div>

      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
          Back
        </Button>
        {step < totalSteps - 1 ? (
          <Button onClick={() => setStep((s) => Math.min(totalSteps - 1, s + 1))}>Next</Button>
        ) : (
          <Button onClick={() => onComplete(setup)}>Start Lesson</Button>
        )}
      </div>
    </Card>
  );
}
