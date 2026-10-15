"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Progress } from "@/components/ui/Progress";
import { VisualAssistOverlay } from "@/components/VisualAssistOverlay";
import { useAudioRecorder } from "@/hooks/useAudioRecorder";
import { ControlMessage, useDuplexSocket } from "@/hooks/useDuplexSocket";
import { LessonSetup, Phase, SessionAssessment } from "@/lib/types";
import { addWeakLexiconTerms } from "@/lib/store";

const PHASE_LABELS: Record<Phase, string> = {
  WARMUP: "Warm-up",
  DRILL: "Drill",
  ROLEPLAY: "Role-play",
  PAUSE: "Paused",
  WRAPUP: "Finished",
  LOCKED: "Locked out",
};

interface LessonRoomProps {
  setup: LessonSetup;
}

/**
 * Main lesson room component.
 *
 * It connects the browser microphone to the backend WebSocket, manages the
 * audio playback queue for model responses, and exposes controls for barge-in
 * interruption and the pull-based visual assist layer.
 */
export function LessonRoom({ setup }: LessonRoomProps) {
  const [phase, setPhase] = useState<Phase>("WARMUP");
  const [transcript, setTranscript] = useState<string>("");
  const [hint, setHint] = useState<string | null>(null);
  const [driftStrikes, setDriftStrikes] = useState(0);
  const [lockoutRemaining, setLockoutRemaining] = useState<number | null>(null);
  const [energy, setEnergy] = useState(0);
  const [sessionElapsed, setSessionElapsed] = useState(0);
  const [connected, setConnected] = useState(false);
  const [visualOpen, setVisualOpen] = useState(false);
  const [isHolding, setIsHolding] = useState(false);
  const [assessment, setAssessment] = useState<SessionAssessment | null>(null);

  // AudioContext + queue refs for full-duplex playback.
  const audioCtxRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef(0);
  const queueRef = useRef<AudioBufferSourceNode[]>([]);

  // Countdown timer.
  useEffect(() => {
    const id = window.setInterval(() => {
      setSessionElapsed((prev) => prev + 1);
      if (lockoutRemaining !== null && lockoutRemaining > 0) {
        setLockoutRemaining((prev) => (prev !== null ? Math.max(0, prev - 1) : null));
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [lockoutRemaining]);

  // Initialize AudioContext lazily and on user gesture.
  const ensureAudioContext = useCallback(async () => {
    if (!audioCtxRef.current) {
      const AudioContextClass =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      audioCtxRef.current = new AudioContextClass({ sampleRate: 24000 });
      nextStartTimeRef.current = audioCtxRef.current.currentTime;
    }
    if (audioCtxRef.current.state === "suspended") {
      await audioCtxRef.current.resume();
    }
    return audioCtxRef.current;
  }, []);

  // Decode + enqueue a base64 PCM16 mono 24kHz chunk into the playback queue.
  const handleAudioChunk = useCallback(
    async (base64Pcm16: string) => {
      if (!base64Pcm16) return;
      const ctx = await ensureAudioContext();
      const raw = atob(base64Pcm16);
      const pcm16 = new Int16Array(raw.length / 2);
      for (let i = 0; i < raw.length; i += 2) {
        pcm16[i / 2] = raw.charCodeAt(i) | (raw.charCodeAt(i + 1) << 8);
      }
      const floats = new Float32Array(pcm16.length);
      for (let i = 0; i < pcm16.length; i++) {
        floats[i] = pcm16[i] / 32768;
      }
      const buffer = ctx.createBuffer(1, floats.length, 24000);
      buffer.copyToChannel(floats, 0);

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);

      const startTime = Math.max(ctx.currentTime, nextStartTimeRef.current);
      source.start(startTime);
      nextStartTimeRef.current = startTime + buffer.duration;
      queueRef.current.push(source);
      source.onended = () => {
        const idx = queueRef.current.indexOf(source);
        if (idx !== -1) queueRef.current.splice(idx, 1);
      };
    },
    [ensureAudioContext]
  );

  // Barge-in: flush the AudioContext playback queue immediately.
  const flushPlayback = useCallback(() => {
    queueRef.current.forEach((source) => {
      try {
        source.stop();
        source.disconnect();
      } catch {
        // Already stopped.
      }
    });
    queueRef.current = [];
    if (audioCtxRef.current) {
      nextStartTimeRef.current = audioCtxRef.current.currentTime;
    }
  }, []);

  const handleControl = useCallback(
    (msg: ControlMessage) => {
      const payload = msg.payload ?? {};
      switch (msg.type) {
        case "STATE_CHANGE":
          if (payload.phase) setPhase(payload.phase as Phase);
          if (typeof payload.drift_strikes === "number") {
            setDriftStrikes(payload.drift_strikes);
          }
          break;
        case "AUDIO_CHUNK":
          // Handled separately via onAudioChunk callback.
          break;
        case "STRIKE_WARNING":
          if (typeof payload.drift_strikes === "number") {
            setDriftStrikes((prev) => Math.max(prev, payload.drift_strikes as number));
          }
          if (typeof payload.note === "string") {
            setTranscript(payload.note);
          }
          break;
        case "LOCKOUT_SIGNAL":
          setPhase("LOCKED");
          if (typeof payload.lockout_remaining_seconds === "number") {
            setLockoutRemaining(payload.lockout_remaining_seconds);
          }
          flushPlayback();
          break;
        case "HINT_RESPONSE":
          if (typeof payload.hint === "string") {
            setHint(payload.hint);
          }
          break;
        case "SESSION_ASSESSMENT": {
          const data = payload.data as SessionAssessment | undefined;
          if (data) {
            const weakTerms = [
              ...data.missed_lexicon,
              ...data.detected_gaps.map((g) => g.phrase),
            ];
            addWeakLexiconTerms(weakTerms);
            setAssessment(data);
            setPhase("WRAPUP");
            flushPlayback();
          }
          break;
        }
        case "ERROR":
          if (typeof payload.message === "string") {
            setTranscript(`Error: ${payload.message}`);
          }
          break;
        case "PONG":
        default:
          break;
      }
    },
    [flushPlayback]
  );

  const ws = useDuplexSocket({
    url: "ws://localhost:8000/ws/audio-tutor",
    setup,
    onMessage: handleControl,
    onAudioChunk: handleAudioChunk,
    onInterrupt: flushPlayback,
  });

  useEffect(() => {
    setConnected(ws.isConnected);
  }, [ws.isConnected]);

  // Forward microphone PCM frames to the backend.
  const onFrame = useCallback(
    (frame: ArrayBuffer, voiceEnergy: number) => {
      setEnergy(voiceEnergy);
      if (voiceEnergy > 0.02) {
        flushPlayback();
      }
      ws.sendAudio(frame);
    },
    [ws, flushPlayback]
  );

  const { isRecording, error: recorderError, start, stop } = useAudioRecorder({
    onFrame,
    sampleRate: 24000,
    frameDurationMs: 100,
  });

  // Start recording after component mounts (microphone already started by LessonIntro)
  useEffect(() => {
    if (setup && !isRecording) {
      console.log("[LessonRoom] Starting microphone recording");
      ensureAudioContext().then(start).catch(console.error);
    }
    return () => {
      stop();
      audioCtxRef.current?.close();
      audioCtxRef.current = null;
    };
  }, [setup, start, stop, ensureAudioContext, isRecording]);

  const handleInterrupt = useCallback(() => {
    flushPlayback();
    ws.sendControl({ type: "HARDWARE_INTERRUPT", payload: {} });
  }, [flushPlayback, ws]);

  const handleHint = useCallback(() => {
    setVisualOpen(true);
    ws.sendControl({ type: "GET_HINT", payload: {} });
  }, [ws]);

  const handleDebrief = useCallback(() => {
    ws.sendControl({ type: "DEBRIEF", payload: {} });
  }, [ws]);

  const closeAssessment = useCallback(() => {
    setAssessment(null);
  }, []);

  const sessionLengthSeconds = (setup?.sessionLengthMinutes ?? 5) * 60;
  const progressPct = Math.min(100, Math.round((sessionElapsed / sessionLengthSeconds) * 100));

  const statusText = useMemo(() => {
    if (lockoutRemaining !== null) return "Session locked";
    if (!connected) return "Reconnecting…";
    return isRecording ? `Listening… energy ${(energy * 100).toFixed(0)}%` : "Microphone off";
  }, [connected, isRecording, energy, lockoutRemaining]);

  const isLockedOut = phase === "LOCKED" || lockoutRemaining !== null;

  return (
    <div className="min-h-screen flex flex-col items-center p-6 gap-6">
      <header className="w-full max-w-3xl flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Audio lesson</h1>
          <p className="text-sm text-muted-foreground">
            {setup.targetLanguage} • {setup.proficiencyLevel}
          </p>
        </div>
        <Badge variant={isLockedOut ? "danger" : phase === "ROLEPLAY" ? "success" : "default"}>
          {PHASE_LABELS[phase]}
        </Badge>
      </header>

      <Card className="w-full max-w-3xl flex flex-col items-center gap-6 p-8">
        <div
          className="relative w-32 h-32 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg"
          aria-label="Coach Alex voice avatar"
        >
          <div
            className="absolute inset-0 rounded-full animate-ping opacity-25 bg-indigo-400"
            style={{ animationDuration: isLockedOut ? "2s" : "1.2s" }}
          />
          <span className="text-4xl" aria-hidden="true">
            🎙️
          </span>
        </div>

        <div className="w-full space-y-2">
          <div className="flex justify-between text-sm">
            <span>Session progress</span>
            <span>{progressPct}%</span>
          </div>
          <Progress value={progressPct} />
        </div>

        <div className="w-full grid grid-cols-2 gap-4 text-sm">
          <div className="rounded-lg border p-3">
            <span className="text-muted-foreground">Status</span>
            <p className="font-medium">{statusText}</p>
            {recorderError && <p className="text-danger text-xs mt-1">{recorderError}</p>}
          </div>
          <div className="rounded-lg border p-3">
            <span className="text-muted-foreground">Drift strikes</span>
            <p className="font-medium">{driftStrikes} / 5</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 justify-center">
          <Button onClick={handleInterrupt} variant="secondary">
            Interrupt / Esc
          </Button>
          <Button onClick={handleHint} variant="outline">
            Get Hint
          </Button>
          <Button onClick={() => setVisualOpen(true)} variant="outline">
            Reveal Transcript
          </Button>
          <Button onClick={handleDebrief} variant="outline">
            End & Review
          </Button>
        </div>
      </Card>

      {assessment && (
        <AssessmentCard assessment={assessment} onClose={closeAssessment} />
      )}

      <VisualAssistOverlay
        isOpen={visualOpen || isHolding}
        liveTranscript={transcript}
        hint={hint}
        onRequestHint={handleHint}
        onHoldChange={setIsHolding}
      />
    </div>
  );
}

function AssessmentCard({
  assessment,
  onClose,
}: {
  assessment: SessionAssessment;
  onClose: () => void;
}) {
  const { scores } = assessment;
  const metrics: { key: keyof typeof scores; label: string }[] = [
    { key: "communicative_success", label: "Communicative Success" },
    { key: "lexical_resource", label: "Lexical Resource" },
    { key: "grammatical_control", label: "Grammatical Control" },
    { key: "fluency", label: "Fluency & Hesitation" },
  ];

  return (
    <Card className="w-full max-w-3xl p-6 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-bold">Lesson Review</h2>
          <p className="text-sm text-muted-foreground">
            Scenario: {assessment.scenario_id} • {new Date(assessment.timestamp).toLocaleString()}
          </p>
        </div>
        <Button onClick={onClose} variant="outline">
          Close
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {metrics.map(({ key, label }) => {
          const score = scores[key];
          return (
            <div key={key} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>{label}</span>
                <span className="font-medium">{score}/5</span>
              </div>
              <Progress value={(score / 5) * 100} />
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
        <div className="rounded-lg border p-3">
          <span className="text-muted-foreground">Target vocabulary used</span>
          {assessment.target_lexicon_used.length > 0 ? (
            <ul className="mt-1 space-y-1">
              {assessment.target_lexicon_used.map((term) => (
                <li key={term} className="text-green-700 dark:text-green-400 font-medium">
                  ✓ {term}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1">No target vocabulary detected this session.</p>
          )}
        </div>
        <div className="rounded-lg border p-3">
          <span className="text-muted-foreground">Missed vocabulary</span>
          {assessment.missed_lexicon.length > 0 ? (
            <ul className="mt-1 space-y-1">
              {assessment.missed_lexicon.map((term) => (
                <li key={term} className="text-amber-700 dark:text-amber-400 font-medium">
                  • {term}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1">Great — you covered the key vocabulary!</p>
          )}
        </div>
      </div>

      {assessment.detected_gaps.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold">Detected gaps</h3>
          <ul className="space-y-2 text-sm">
            {assessment.detected_gaps.map((gap, idx) => (
              <li key={idx} className="rounded-lg border p-3">
                <span className="font-medium">{gap.phrase}</span>
                <span className="ml-2 text-xs uppercase text-muted-foreground">{gap.type}</span>
                <p className="mt-1 text-muted-foreground">{gap.issue}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex justify-end gap-3">
        <Button onClick={onClose} variant="secondary">
          Save progress & return
        </Button>
      </div>
    </Card>
  );
}
