"use client";

import { useCallback, useRef, useState } from "react";

export interface AudioEnergyEvent {
  energy: number;
  isActive: boolean;
}

interface UseAudioRecorderOptions {
  sampleRate?: number;
  bufferSize?: number;
  frameDurationMs?: number;
  onDataAvailable?: (chunk: ArrayBuffer) => void;
  onEnergy?: (event: AudioEnergyEvent) => void;
  /**
   * Convenience callback that fires for every audio chunk together with the
   * current voice-activity energy level. Used by the lesson room to stream
   * audio to the backend and trigger barge-in interruption.
   */
  onFrame?: (chunk: ArrayBuffer, energy: number) => void;
}

interface UseAudioRecorderReturn {
  isRecording: boolean;
  error: string | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

/**
 * Hook that captures raw PCM microphone audio via the Web Audio API and reports
 * energy levels for barge-in interruption detection.
 *
 * Defaults:
 * - sampleRate: 16000 Hz
 * - channel count: 1 (mono)
 * - bit depth: 16-bit PCM
 */
export function useAudioRecorder(
  options: UseAudioRecorderOptions = {}
): UseAudioRecorderReturn {
  const { sampleRate = 16000, bufferSize = 4096, onDataAvailable, onEnergy, onFrame } = options;

  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<AudioWorkletNode | ScriptProcessorNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const energyIntervalRef = useRef<number | null>(null);
  const latestEnergyRef = useRef(0);

  const handleData = useCallback(
    (chunk: ArrayBuffer) => {
      console.log(`[AudioRecorder] Data callback: ${chunk.byteLength} bytes`);
      onDataAvailable?.(chunk);
      onFrame?.(chunk, latestEnergyRef.current);
    },
    [onDataAvailable, onFrame]
  );

  const handleEnergy = useCallback(
    (event: AudioEnergyEvent) => {
      onEnergy?.(event);
    },
    [onEnergy]
  );

  const start = useCallback(async () => {
    console.log("[AudioRecorder] start() called - requesting microphone access");
    setError(null);
    try {
      console.log("[AudioRecorder] Requesting getUserMedia with constraints:", { sampleRate, channelCount: 1 });
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      console.log("[AudioRecorder] ✓ Microphone access granted");
      streamRef.current = stream;

      console.log("[AudioRecorder] Creating AudioContext with sampleRate:", sampleRate);
      const audioContext = new AudioContext({ sampleRate });
      audioContextRef.current = audioContext;
      console.log(`[AudioRecorder] AudioContext created, initial state: ${audioContext.state}`);

      const source = audioContext.createMediaStreamSource(stream);
      console.log("[AudioRecorder] Created MediaStreamSource from microphone");

      // Analyser for barge-in / voice-activity detection.
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.7;
      source.connect(analyser);
      analyserRef.current = analyser;
      console.log("[AudioRecorder] Created and connected AnalyserNode");

      energyIntervalRef.current = window.setInterval(() => {
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(data);
        const average = data.reduce((sum, v) => sum + v, 0) / data.length;
        latestEnergyRef.current = average / 255; // normalize to [0, 1]
        handleEnergy({ energy: average, isActive: average > 20 });
      }, 100);
      console.log("[AudioRecorder] Started energy monitoring interval (100ms)");

      // Load AudioWorklet processor when available.
      let processor: AudioWorkletNode | ScriptProcessorNode;
      
      try {
        console.log("[AudioRecorder] Attempting to load AudioWorklet: /audio-worklet/pcm-processor.js");
        await audioContext.audioWorklet.addModule("/audio-worklet/pcm-processor.js");
        const worklet = new AudioWorkletNode(audioContext, "pcm-processor", {
          processorOptions: { bufferSize },
        });
        worklet.port.onmessage = (event) => {
          if (event.data instanceof ArrayBuffer) {
            handleData(event.data);
          }
        };
        processor = worklet;
        console.log("[AudioRecorder] ✓ AudioWorklet loaded and processor created");
      } catch (workletErr) {
        console.warn("[AudioRecorder] AudioWorklet failed, falling back to ScriptProcessorNode:", workletErr);
        const fallback = audioContext.createScriptProcessor(bufferSize, 1, 1);
        fallback.onaudioprocess = (event) => {
          const input = event.inputBuffer.getChannelData(0);
          const pcm16 = float32ToInt16(input);
          handleData(pcm16.buffer as ArrayBuffer);
        };
        processor = fallback;
        console.log("[AudioRecorder] ✓ ScriptProcessorNode fallback created");
      }

      source.connect(processor);
      processor.connect(audioContext.destination);
      processorRef.current = processor;
      console.log("[AudioRecorder] Audio graph connected: source → processor → destination");
      
      // Ensure AudioContext is running
      if (audioContext.state === "suspended") {
        console.log("[AudioRecorder] Resuming suspended AudioContext");
        await audioContext.resume();
      }
      console.log(`[AudioRecorder] ✓ AudioContext state: ${audioContext.state}`);
      
      setIsRecording(true);
      console.log("[AudioRecorder] ✓ Recording started successfully");
    } catch (err) {
      console.error("[AudioRecorder] ✗ Failed to start microphone:", err);
      setError(err instanceof Error ? err.message : "Failed to start microphone");
      setIsRecording(false);
    }
  }, [sampleRate, bufferSize, handleData, handleEnergy]);

  const stop = useCallback(async () => {
    console.log("[AudioRecorder] stop() called");
    if (energyIntervalRef.current) {
      window.clearInterval(energyIntervalRef.current);
      energyIntervalRef.current = null;
      console.log("[AudioRecorder] Cleared energy interval");
    }

    processorRef.current?.disconnect();
    processorRef.current = null;
    console.log("[AudioRecorder] Disconnected processor");

    await audioContextRef.current?.close();
    audioContextRef.current = null;
    analyserRef.current = null;
    console.log("[AudioRecorder] Closed AudioContext");

    streamRef.current?.getTracks().forEach((track) => {
      track.stop();
      console.log("[AudioRecorder] Stopped microphone track");
    });
    streamRef.current = null;

    setIsRecording(false);
    console.log("[AudioRecorder] ✓ Recording stopped");
  }, []);

  return {
    isRecording,
    error,
    start,
    stop,
  };
}

function float32ToInt16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}
