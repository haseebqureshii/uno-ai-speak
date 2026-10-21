use client;

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useDuplexSocket } from "@/hooks/useDuplexSocket";
import { ControlMessage, LessonSetup } from "@/lib/types";

type CaptionSegment = {
  start_ms: number;
  end_ms: number;
  text: string;
};

type CaptionUpdatePayload = {
  speaker: "coach" | "user" | string;
  text: string;
  segments?: CaptionSegment[];
  turn_id?: string;
  timestamp?: number;
};

type CaptionUpdateMessage = ControlMessage & {
  type: "CAPTION_UPDATE";
  payload: CaptionUpdatePayload;
};

type CaptionTurn = {
  id: string;
  speaker: string;
  text: string;
  segments?: CaptionSegment[];
  receivedAt: number;
};

interface AmbientCaptionsProps {
  url: string;
  setup: LessonSetup | null;
  className?: string;
}

export function AmbientCaptions({ url, setup, className }: AmbientCaptionsProps) {
  const [captions, setCaptions] = useState<CaptionTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now());
  const containerRef = useRef<HTMLDivElement>(null);
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    const tick = () => {
      setNow(Date.now());
      animationRef.current = requestAnimationFrame(tick);
    };
    animationRef.current = requestAnimationFrame(tick);
    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
    };
  }, []);

  const handleMessage = (msg: ControlMessage) => {
    if (msg.type === "CAPTION_UPDATE") {
      const update = msg as CaptionUpdateMessage;
      const payload = update.payload;
      if (!payload?.text) return;
      const id = payload.turn_id ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const turn: CaptionTurn = {
        id,
        speaker: payload.speaker ?? "coach",
        text: payload.text,
        segments: payload.segments,
        receivedAt: Date.now(),
      };
      setCaptions((prev) => {
        if (prev.find((t) => t.id === id)) return prev;
        return [...prev, turn];
      });
    }
  };

  const { isConnected, error: socketError } = useDuplexSocket({
    url,
    setup,
    onMessage: handleMessage,
  });

  useEffect(() => {
    setError(socketError);
  }, [socketError]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [captions.length]);

  const renderedTurns = useMemo(() => {
    return captions.map((turn) => {
      const elapsed = now - turn.receivedAt;
      let activeIndex = -1;
      if (turn.segments && turn.segments.length > 0) {
        activeIndex = turn.segments.findIndex(
          (s) => elapsed >= s.start_ms && elapsed < s.end_ms
        );
        if (activeIndex === -1 && elapsed >= turn.segments[turn.segments.length - 1].end_ms) {
          activeIndex = turn.segments.length - 1;
        }
      }

      const content =
        turn.segments && turn.segments.length > 0 ? (
        <span>
          {turn.segments.map((seg, i) => {
            const isActive = i === activeIndex;
            return (
              <span
                key={i}
                className={isActive ? "caption-segment caption-segment-active" : "caption-segment"}
                aria-current={isActive ? "true" : undefined}
              >
                {seg.text}
              </span>
            );
          })}
        </span>
      ) : (
        <span>{turn.text}</span>
      );

      return (
        <article key={turn.id} className="caption-turn" aria-label={`${turn.speaker} caption`}>
          <header className="caption-turn-header">
            <span className="caption-speaker">{turn.speaker}</span>
            <time dateTime={new Date(turn.receivedAt).toISOString()} className="caption-time">
              {new Date(turn.receivedAt).toLocaleTimeString()}
            </time>
          </header>
          <p className="caption-text">{content}</p>
        </article>
      );
    });
  }, [captions, nowRef.current]);

  if (!setup) {
    return (
      <div className={className} role="status" aria-live="polite">
        <p>Waiting for lesson setup…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={className} role="alert">
        <p>Connection error: {error}</p>
      </div>
    );
  }

  return (
    <section className={className ?? "ambient-captions"} aria-label="Ambient captions feed">
      <div className="ambient-captions-status" aria-live="polite">
        {isConnected ? "Live" : "Connecting…"}
      </div>
      <div
        ref={containerRef}
        className="ambient-captions-feed"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        {captions.length === 0 ? (
          <p className="ambient-captions-empty">No captions yet</p>
        ) : (
          renderedTurns
        )}
      </div>
    </section>
  );
}

export default AmbientCaptions;