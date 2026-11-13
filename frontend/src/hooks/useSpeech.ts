"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

// The Web Speech API is not in lib.dom.d.ts, so describe only what is used.
interface SpeechResultLike {
  isFinal: boolean;
  0: { transcript: string };
}
interface SpeechEventLike {
  resultIndex: number;
  results: { length: number; [i: number]: SpeechResultLike };
}
interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SpeechEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => RecognitionLike;

function getCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const ERRORS: Record<string, string> = {
  "not-allowed": "Microphone access was blocked. Allow it in the browser's address bar and try again.",
  "service-not-allowed": "Microphone access was blocked. Allow it in the browser's address bar and try again.",
  "audio-capture": "No microphone was found.",
  "no-speech": "I did not hear anything. Try again.",
  network: "Voice input needs an internet connection.",
};

export const SPEECH_UNSUPPORTED = "Voice input is not supported in this browser. Try Chrome or Edge, or type your answer.";

interface Options {
  /** Called with each finished piece of speech (already trimmed). */
  onFinal: (text: string) => void;
  lang?: string;
}

/** Speech-to-text with the browser's SpeechRecognition: { supported, listening, interim, error, start, stop, toggle }. */
export function useSpeech({ onFinal, lang = "en-US" }: Options) {
  const supported = useSyncExternalStore(
    () => () => {},
    () => getCtor() !== null,
    () => false,
  );
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<RecognitionLike | null>(null);
  const onFinalRef = useRef(onFinal);
  useEffect(() => {
    onFinalRef.current = onFinal;
  });

  const stop = useCallback(() => {
    rec.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = getCtor();
    if (!Ctor) {
      setError(SPEECH_UNSUPPORTED);
      return;
    }
    if (rec.current) return;
    const r = new Ctor();
    r.lang = lang;
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (e) => {
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const piece = e.results[i];
        const text = piece[0].transcript;
        if (piece.isFinal) {
          const clean = text.trim();
          if (clean) onFinalRef.current(clean);
        } else {
          live += text;
        }
      }
      setInterim(live.trim());
    };
    r.onerror = (e) => {
      if (e.error !== "aborted") setError(ERRORS[e.error] ?? "Voice input stopped unexpectedly.");
    };
    r.onend = () => {
      rec.current = null;
      setListening(false);
      setInterim("");
    };
    rec.current = r;
    setError(null);
    try {
      r.start();
      setListening(true);
    } catch {
      rec.current = null;
      setError("Could not start the microphone.");
    }
  }, [lang]);

  const toggle = useCallback(() => (rec.current ? stop() : start()), [start, stop]);

  useEffect(() => () => rec.current?.abort(), []);

  return { supported, listening, interim, error, start, stop, toggle };
}
