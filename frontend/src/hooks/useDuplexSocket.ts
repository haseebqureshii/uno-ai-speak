"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ControlMessage, LessonSetup } from "@/lib/types";

export type { ControlMessage };

interface UseDuplexSocketOptions {
  url: string;
  setup: LessonSetup | null;
  onMessage: (msg: ControlMessage) => void;
  onAudioChunk?: (pcm16Base64: string) => void;
  onInterrupt?: () => void;
}

interface UseDuplexSocketReturn {
  isConnected: boolean;
  error: string | null;
  sendAudio: (bytes: ArrayBuffer) => void;
  sendControl: (message: Omit<ControlMessage, "source">) => void;
}

/**
 * Hook that manages a full-duplex WebSocket to the audio tutor backend.
 *
 * Responsibilities:
 * - Open the socket and send the SETUP handshake immediately.
 * - Send binary audio frames and JSON control frames.
 * - Parse incoming JSON control frames (STATE_CHANGE, INTERRUPT_SIGNAL,
 *   STRIKE_WARNING, LOCKOUT_SIGNAL, HINT_RESPONSE, AUDIO_CHUNK, ERROR, PONG).
 * - Listen for hardware interrupt keys (Escape) and forward them as control frames.
 */
export function useDuplexSocket({
  url,
  setup,
  onMessage,
  onAudioChunk,
  onInterrupt,
}: UseDuplexSocketOptions): UseDuplexSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const setupRef = useRef(setup);

  useEffect(() => {
    setupRef.current = setup;
  }, [setup]);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      console.log("[WebSocket] Already connected, skipping reconnect");
      return;
    }

    console.log(`[WebSocket] Attempting to connect to: ${url}`);

    try {
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";

      const sendSetup = (target: WebSocket) => {
        const currentSetup = setupRef.current;
        if (!currentSetup || target.readyState !== WebSocket.OPEN) {
          console.log("[WebSocket] Cannot send SETUP - no setup or socket not open");
          return;
        }
        const setupPayload = {
          type: "SETUP",
          payload: {
            client_id: currentSetup.clientId,
            target_language: currentSetup.targetLanguage,
            home_language: currentSetup.homeLanguage,
            proficiency_level: currentSetup.proficiencyLevel,
            session_length_minutes: currentSetup.sessionLengthMinutes,
            lockout_cooldown_minutes: currentSetup.lockoutCooldownMinutes,
            weak_lexicon: currentSetup.weakLexicon ?? [],
          },
        };
        console.log("[WebSocket] Sending SETUP payload:", JSON.stringify(setupPayload, null, 2));
        target.send(JSON.stringify(setupPayload));
      };

      ws.onopen = () => {
        console.log("[WebSocket] ✓ Connection established (onopen)");
        setIsConnected(true);
        setError(null);
        // Re-transmit the last SETUP on every (re)connect so the backend can
        // rebuild its in-memory FSM/AppState after a disconnect.
        sendSetup(ws);
      };

      ws.onclose = (event) => {
        console.log(`[WebSocket] ✗ Connection closed (onclose) - Code: ${event.code}, Reason: ${event.reason}, Clean: ${event.wasClean}`);
        setIsConnected(false);
        if (!event.wasClean) {
          console.log("[WebSocket] Unclean close - scheduling reconnect in 3s");
          reconnectTimerRef.current = window.setTimeout(connect, 3000);
        }
      };

      ws.onerror = (event) => {
        console.error("[WebSocket] ✗ Error (onerror):", event);
        setError("WebSocket error");
      };

      ws.onmessage = (event) => {
        console.log(`[WebSocket] ← Received message (${event.data instanceof ArrayBuffer ? "binary" : "text"}): ${event.data instanceof ArrayBuffer ? `${(event.data as ArrayBuffer).byteLength} bytes` : event.data.substring(0, 150)}`);
        
        if (event.data instanceof ArrayBuffer) {
          // Not used currently; server sends audio as base64 JSON frames.
          console.log("[WebSocket] Binary message ignored (server uses JSON AUDIO_CHUNK)");
          return;
        }
        try {
          const msg = JSON.parse(event.data as string) as ControlMessage;
          console.log(`[WebSocket] Parsed control frame: type=${msg.type}, source=${msg.source}, reason=${msg.reason}`);
          
          if (msg.type === "AUDIO_CHUNK" && typeof msg.payload === "object" && msg.payload !== null) {
            const base64 = msg.payload.audio as string | undefined;
            if (base64 && onAudioChunk) {
              console.log(`[WebSocket] AUDIO_CHUNK: ${base64.length} chars base64`);
              onAudioChunk(base64);
            }
          }
          onMessage(msg);
          if (msg.type === "INTERRUPT_SIGNAL" || msg.type === "LOCKOUT_SIGNAL") {
            console.log(`[WebSocket] Triggering interrupt for ${msg.type}`);
            onInterrupt?.();
          }
        } catch (parseErr) {
          console.error("[WebSocket] Failed to parse JSON control frame:", parseErr);
          setError("Received invalid JSON control frame");
        }
      };

      socketRef.current = ws;
      console.log("[WebSocket] WebSocket instance created, waiting for onopen...");
    } catch (err) {
      console.error("[WebSocket] Failed to create WebSocket:", err);
      setError(err instanceof Error ? err.message : "Failed to open WebSocket");
    }
  }, [url, onMessage, onAudioChunk, onInterrupt]);

  useEffect(() => {
    console.log("[WebSocket] useEffect triggered, calling connect()");
    connect();
    return () => {
      console.log("[WebSocket] useEffect cleanup");
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [connect]);

  // If the stored setup changes (or becomes available) while already connected,
  // re-transmit SETUP so the backend state stays in sync.
  useEffect(() => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !setup) {
      console.log("[WebSocket] Skipping SETUP retransmit - socket not open or no setup");
      return;
    }
    console.log("[WebSocket] Setup changed, re-transmitting SETUP");
    ws.send(
      JSON.stringify({
        type: "SETUP",
        payload: {
          client_id: setup.clientId,
          target_language: setup.targetLanguage,
          home_language: setup.homeLanguage,
          proficiency_level: setup.proficiencyLevel,
          session_length_minutes: setup.sessionLengthMinutes,
          lockout_cooldown_minutes: setup.lockoutCooldownMinutes,
          weak_lexicon: setup.weakLexicon ?? [],
        },
      })
    );
  }, [setup, isConnected]);

  // Hardware interrupt listener: forward Escape key as HARDWARE_INTERRUPT.
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        console.log("[WebSocket] Escape key pressed - sending HARDWARE_INTERRUPT");
        sendControl({ type: "HARDWARE_INTERRUPT", payload: {} });
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  const sendAudio = useCallback((bytes: ArrayBuffer) => {
    const ws = socketRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(bytes);
    } else {
      console.warn("[WebSocket] Cannot send audio - socket not open");
    }
  }, []);

  const sendControl = useCallback((message: Omit<ControlMessage, "source">) => {
    const ws = socketRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      const fullMessage = { ...message, source: "client" as const };
      console.log(`[WebSocket] → Sending control frame: ${message.type}`);
      ws.send(JSON.stringify(fullMessage));
    } else {
      console.warn("[WebSocket] Cannot send control - socket not open");
    }
  }, []);

  return {
    isConnected,
    error,
    sendAudio,
    sendControl,
  };
}
