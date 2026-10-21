import { useEffect, useRef, useState } from "react";

export interface ControlMessage {
  type: string;
  [key: string]: any;
}

export interface LessonSetup {
  client_id: string;
  target_language: string;
  home_language: string;
  proficiency_level: string;
  session_length_minutes: number;
  lockout_cooldown_minutes: number;
  provider: string;
  weak_lexicon: string[];
}

interface UseDuplexSocketProps {
  url: string;
  setup: LessonSetup | null;
  onMessage: (msg: ControlMessage) => void;
}

export function useDuplexSocket({ url, setup, onMessage }: UseDuplexSocketProps) {
  const socketRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!setup) return;

    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      setIsConnected(true);
      setError(null);
      // Send SETUP message
      socket.send(JSON.stringify({
        type: "SETUP",
        payload: setup
      }));
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (err) {
        console.error("Failed to parse message:", err);
      }
    };

    socket.onerror = (event) => {
      setError("WebSocket error occurred");
    };

    socket.onclose = () => {
      setIsConnected(false);
      socketRef.current = null;
    };

    return () => {
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    };
  }, [url, setup, onMessage]);

  return { isConnected, error };
}