"use client";

import { useEffect, useRef, useState } from "react";
import { Card, CardDescription, CardHeader, CardTitle, Button } from "@/components/ui";

interface VisualAssistOverlayProps {
  isOpen: boolean;
  hint: string | null;
  liveTranscript: string;
  onRequestHint: () => void;
  onHoldChange?: (isHeld: boolean) => void;
}

/**
 * Pull-based visual assistance panel.
 *
 * - Hidden by default.
 * - The user can press and hold spacebar (or a hold button) to temporarily reveal
 *   live transcript tokens. The panel hides automatically on release.
 * - A "Get Hint" button fetches an on-demand contextual hint.
 */
export function VisualAssistOverlay({
  isOpen,
  hint,
  liveTranscript,
  onRequestHint,
  onHoldChange,
}: VisualAssistOverlayProps) {
  const [isHolding, setIsHolding] = useState(false);
  const holdRef = useRef(false);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (event.code === "Space" && !holdRef.current) {
        event.preventDefault();
        holdRef.current = true;
        setIsHolding(true);
        onHoldChange?.(true);
      }
    };
    const up = (event: KeyboardEvent) => {
      if (event.code === "Space" && holdRef.current) {
        event.preventDefault();
        holdRef.current = false;
        setIsHolding(false);
        onHoldChange?.(false);
      }
    };

    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [onHoldChange]);

  const revealTranscript = isHolding || isOpen;

  return (
    <Card
      className={`transition-all ${
        isOpen ? "opacity-100" : "pointer-events-none opacity-0"
      }`}
    >
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">Visual Assist</CardTitle>
            <CardDescription>Pull-based help. Hold spacebar to peek at the transcript.</CardDescription>
          </div>
          <Button variant="secondary" size="sm" onClick={onRequestHint}>
            Get Hint
          </Button>
        </div>
      </CardHeader>

      <div className="space-y-4">
        <div
          className={`rounded-lg border p-3 transition ${
            revealTranscript
              ? "border-slate-300 bg-white"
              : "border-dashed border-slate-200 bg-slate-50"
          }`}
        >
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Live Transcript
          </p>
          <p className="min-h-[1.5rem] text-sm text-slate-700">
            {revealTranscript ? liveTranscript || "(listening…)" : "Hold spacebar to reveal"}
          </p>
        </div>

        {hint && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-700">
              Hint
            </p>
            <p className="text-sm text-amber-900">{hint}</p>
          </div>
        )}

        <button
          type="button"
          className="w-full select-none rounded-lg border border-slate-300 bg-white py-3 text-sm font-medium text-slate-700 active:bg-slate-100"
          onMouseDown={() => {
            setIsHolding(true);
            onHoldChange?.(true);
          }}
          onMouseUp={() => {
            setIsHolding(false);
            onHoldChange?.(false);
          }}
          onMouseLeave={() => {
            setIsHolding(false);
            onHoldChange?.(false);
          }}
          onTouchStart={() => {
            setIsHolding(true);
            onHoldChange?.(true);
          }}
          onTouchEnd={() => {
            setIsHolding(false);
            onHoldChange?.(false);
          }}
        >
          {isHolding ? "Releasing will hide transcript" : "Hold to reveal transcript"}
        </button>
      </div>
    </Card>
  );
}
