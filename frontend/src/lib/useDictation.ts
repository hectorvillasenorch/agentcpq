import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Minimal types for the Web Speech API. SpeechRecognition is not part of the
 * standard TS DOM lib yet, so we type only what we use.
 */
interface SpeechRecognitionInstance {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

interface SpeechRecognitionEvent {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
  }>;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

interface DictationOptions {
  /** Live text as you speak: accumulated finals + the current interim result. */
  onUpdate: (text: string) => void;
  /** Clean, finalized text once listening stops. */
  onFinalize: (text: string) => void;
}

export interface Dictation {
  supported: boolean;
  listening: boolean;
  error: string | null;
  toggle: () => void;
  stop: () => void;
}

function recognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function isDictationSupported(): boolean {
  return recognitionCtor() !== null;
}

export function useDictation({ onUpdate, onFinalize }: DictationOptions): Dictation {
  const supported = isDictationSupported();
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<SpeechRecognitionInstance | null>(null);
  const onUpdateRef = useRef(onUpdate);
  const onFinalizeRef = useRef(onFinalize);
  onUpdateRef.current = onUpdate;
  onFinalizeRef.current = onFinalize;

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    setError(null);
    const rec = new Ctor();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    let finalText = "";
    rec.onresult = (event) => {
      let interim = "";
      let finals = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) finals += transcript;
        else interim += transcript;
      }
      if (finals.trim()) finalText += (finalText ? " " : "") + finals.trim();
      const live = [finalText, interim.trim()].filter(Boolean).join(" ");
      onUpdateRef.current(live);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      if (finalText.trim()) onFinalizeRef.current(finalText.trim());
    };
    rec.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError("Microphone permission denied — allow mic access for this site and try again.");
      } else if (event.error === "no-speech") {
        // Keep listening; the user just paused.
      } else if (event.error !== "aborted") {
        setError(`Dictation unavailable (${event.error}).`);
      }
    };
    recRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch {
      setError("Could not start dictation.");
      recRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    recRef.current?.stop();
  }, []);

  const toggle = useCallback(() => {
    if (listening) stop();
    else start();
  }, [listening, start, stop]);

  useEffect(
    () => () => {
      recRef.current?.abort();
    },
    []
  );

  return { supported, listening, error, toggle, stop };
}
