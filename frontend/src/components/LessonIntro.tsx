"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { useAudioRecorder } from "@/hooks/useAudioRecorder";
import { ControlMessage, useDuplexSocket } from "@/hooks/useDuplexSocket";
import { LessonSetup } from "@/lib/types";

interface LessonIntroProps {
  setup: LessonSetup;
  onComplete: () => void;
}

/**
 * Lesson intro screen that plays Coach Alex's opening message
 * before enabling user microphone input.
 */
export function LessonIntro({ setup, onComplete }: LessonIntroProps) {
  const [coachSpeaking, setCoachSpeaking] = useState(true);
  const [transcript, setTranscript] = useState<string>("");
  const [connected, setConnected] = useState(false);
  const [waitingForUser, setWaitingForUser] = useState(false);

  // Audio playback refs
  const audioCtxRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef(0);
  const queueRef = useRef<AudioBufferSourceNode[]>([]);

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
        
        // If queue is empty and we're still in intro, coach finished speaking
        if (queueRef.current.length === 0 && coachSpeaking) {
          console.log("[LessonIntro] Coach Alex finished speaking");
          setCoachSpeaking(false);
          setWaitingForUser(true);
        }
      };
    },
    [ensureAudioContext, coachSpeaking]
  );

  const handleControl = useCallback(
    (msg: ControlMessage) => {
      const payload = msg.payload ?? {};
      console.log("[LessonIntro] Control message:", msg.type, msg.reason);
      
      switch (msg.type) {
        case "STATE_CHANGE":
          // Session initialized, waiting for coach to finish
          break;
        case "INTERRUPT_SIGNAL":
          // Coach might be pausing
          break;
        default:
          break;
      }
    },
    []
  );

  const ws = useDuplexSocket({
    url: "ws://localhost:8000/ws/audio-tutor",
    setup,
    onMessage: handleControl,
    onAudioChunk: handleAudioChunk,
    onInterrupt: () => {
      // Flush playback queue if needed
      queueRef.current.forEach((source) => {
        try {
          source.stop();
          source.disconnect();
        } catch {}
      });
      queueRef.current = [];
    },
  });

  useEffect(() => {
    setConnected(ws.isConnected);
  }, [ws.isConnected]);

  // Initialize audio context on mount
  useEffect(() => {
    ensureAudioContext().catch(console.error);
    return () => {
      audioCtxRef.current?.close();
    };
  }, [ensureAudioContext]);

  // Start microphone after coach finishes speaking
  const onFrame = useCallback(
    (frame: ArrayBuffer, voiceEnergy: number) => {
      if (waitingForUser) {
        ws.sendAudio(frame);
      }
    },
    [ws, waitingForUser]
  );

  const { isRecording, start: startRecording, stop: stopRecording } = useAudioRecorder({
    onFrame,
    sampleRate: 24000,
    frameDurationMs: 100,
  });

  // Start microphone when waiting for user
  useEffect(() => {
    if (waitingForUser && !isRecording) {
      console.log("[LessonIntro] Starting microphone - waiting for user input");
      startRecording().catch(console.error);
    }
  }, [waitingForUser, isRecording, startRecording]);

  const handleSkip = useCallback(() => {
    console.log("[LessonIntro] User skipped intro");
    onComplete();
  }, [onComplete]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-slate-900 dark:to-slate-950">
      <div className="w-full max-w-2xl space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white">
            Welcome to Your Lesson
          </h1>
          <p className="text-slate-600 dark:text-slate-400">
            {setup.targetLanguage} • Level {setup.proficiencyLevel}
          </p>
        </div>

        {/* Coach Avatar */}
        <div className="flex justify-center">
          <div
            className={`relative w-40 h-40 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-2xl ${
              coachSpeaking ? "animate-pulse" : ""
            }`}
          >
            {coachSpeaking && (
              <div className="absolute inset-0 rounded-full bg-indigo-400 opacity-25 animate-ping" />
            )}
            <span className="text-6xl" aria-hidden="true">
              🎙️
            </span>
          </div>
        </div>

        {/* Status Card */}
        <Card className="p-8 dark:bg-slate-900 dark:border-slate-800">
          <div className="space-y-4">
            {/* Status Badge */}
            <div className="flex justify-center">
              {coachSpeaking ? (
                <Badge variant="default" className="text-sm">
                  🗣️ Coach Alex is speaking...
                </Badge>
              ) : waitingForUser ? (
                <Badge variant="success" className="text-sm">
                  ✓ Ready for you to speak
                </Badge>
              ) : (
                <Badge variant="secondary" className="text-sm">
                  ⏳ Connecting...
                </Badge>
              )}
            </div>

            {/* Transcript Display */}
            <div className="min-h-[120px] rounded-lg border border-slate-200 dark:border-slate-700 p-4 bg-white dark:bg-slate-950">
              {transcript ? (
                <p className="text-lg text-slate-800 dark:text-slate-200 leading-relaxed">
                  {transcript}
                </p>
              ) : coachSpeaking ? (
                <p className="text-slate-500 dark:text-slate-400 italic text-center py-8">
                  Coach Alex is introducing the lesson...
                </p>
              ) : waitingForUser ? (
                <p className="text-slate-600 dark:text-slate-300 text-center py-8">
                  <strong>Microphone is active.</strong><br />
                  You can now speak and respond to Coach Alex.
                </p>
              ) : (
                <p className="text-slate-500 dark:text-slate-400 text-center py-8">
                  Initializing...
                </p>
              )}
            </div>

            {/* Progress Indicators */}
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                <span className="text-slate-500 dark:text-slate-400">Connection</span>
                <p className="font-medium text-slate-800 dark:text-slate-200">
                  {connected ? "✓ Connected" : "⏳ Connecting..."}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                <span className="text-slate-500 dark:text-slate-400">Microphone</span>
                <p className="font-medium text-slate-800 dark:text-slate-200">
                  {isRecording ? "✓ Active" : waitingForUser ? "⏳ Starting..." : "⏸️ Waiting"}
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex justify-center gap-3 pt-4">
              {coachSpeaking ? (
                <Button onClick={handleSkip} variant="outline">
                  Skip intro
                </Button>
              ) : waitingForUser ? (
                <Button onClick={onComplete} className="w-full">
                  Start Practicing →
                </Button>
              ) : (
                <Button disabled className="w-full">
                  Waiting for Coach Alex...
                </Button>
              )}
            </div>
          </div>
        </Card>

        {/* Instructions */}
        <div className="text-center text-sm text-slate-500 dark:text-slate-400">
          <p>💡 Tip: Make sure your microphone is working and you're in a quiet space.</p>
        </div>
      </div>
    </div>
  );
}
