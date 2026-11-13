"use client";

import { Mic, MicOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const BARS = [0.5, 0.9, 0.65, 1, 0.55, 0.8, 0.45];

/** Animated bars shown while recording (static when the visitor prefers reduced motion). */
export function Waveform({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cn("flex h-5 items-center gap-0.5", className)}>
      {BARS.map((h, i) => (
        <span
          key={i}
          className="w-0.5 origin-center rounded-full bg-primary motion-safe:animate-[wave_1s_ease-in-out_infinite]"
          style={{ height: `${h * 100}%`, animationDelay: `${i * 0.11}s` }}
        />
      ))}
    </span>
  );
}

interface VoiceButtonProps {
  listening: boolean;
  supported: boolean;
  disabled?: boolean;
  onToggle: () => void;
}

/** Mic toggle for the composer. When unsupported it stays visible (disabled look) and onToggle shows the fallback message. */
export function VoiceButton({ listening, supported, disabled, onToggle }: VoiceButtonProps) {
  return (
    <Button
      type="button"
      variant={listening ? "default" : "outline"}
      size="icon"
      disabled={disabled}
      onClick={onToggle}
      aria-pressed={listening}
      aria-label={listening ? "Stop voice input" : "Start voice input"}
      title={supported ? (listening ? "Stop recording" : "Answer by voice") : "Voice input is not supported in this browser"}
      className={cn("shrink-0", !supported && "opacity-60", listening && "animate-pulse")}
    >
      {listening ? <MicOff /> : <Mic />}
    </Button>
  );
}
