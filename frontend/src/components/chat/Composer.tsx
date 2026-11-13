"use client";

import { Loader2, SendHorizontal } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { VoiceButton, Waveform } from "@/components/chat/VoiceButton";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SPEECH_UNSUPPORTED, useSpeech } from "@/hooks/useSpeech";
import { LIMITS } from "@/lib/interview";
import { cn } from "@/lib/utils";

interface ComposerProps {
  /** Resolves false when sending failed: the text is put back so nothing is lost. */
  onSend: (text: string) => Promise<boolean>;
  disabled: boolean;
  maxLength?: number;
}

const MAX_HEIGHT_PX = 200;

export function Composer({ onSend, disabled, maxLength = LIMITS.answerMax }: ComposerProps) {
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const [voiceNote, setVoiceNote] = useState<string | null>(null);
  const addSpeech = useCallback(
    (piece: string) => setText((t) => `${t && !/\s$/.test(t) ? `${t} ` : t}${piece}`.slice(0, maxLength)),
    [maxLength],
  );
  const speech = useSpeech({ onFinal: addSpeech });
  const { listening, stop: stopSpeech } = speech;
  const trimmed = text.trim();
  const canSend = !disabled && trimmed.length > 0 && trimmed.length <= maxLength;
  const nearLimit = text.length >= maxLength * 0.9;

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [text]);

  useEffect(() => {
    if (!disabled) area.current?.focus();
    else stopSpeech(); // Alex is replying: stop recording
  }, [disabled, stopSpeech]);

  function toggleVoice() {
    if (!speech.supported) return setVoiceNote(SPEECH_UNSUPPORTED);
    setVoiceNote(null);
    speech.toggle();
  }

  async function submit() {
    if (!canSend) return;
    const value = trimmed;
    stopSpeech();
    setText("");
    const ok = await onSend(value);
    if (!ok) setText(value);
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="border-t border-border bg-background/90 px-4 pt-3 pb-4 backdrop-blur sm:px-6"
    >
      {listening && (
        <div className="mx-auto mb-2 flex w-full max-w-3xl items-center gap-3 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-sm" role="status">
          <Waveform />
          <span className="min-w-0 flex-1 truncate text-muted-foreground">{speech.interim || "Listening… speak your answer"}</span>
        </div>
      )}
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
        <Textarea
          ref={area}
          value={text}
          rows={1}
          maxLength={maxLength}
          disabled={disabled}
          placeholder={disabled ? "Alex is replying…" : "Type your answer…"}
          aria-label="Your answer"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <VoiceButton listening={listening} supported={speech.supported} disabled={disabled} onToggle={toggleVoice} />
        <Button type="submit" size="icon" disabled={!canSend} aria-label="Send answer" className="shrink-0">
          {disabled ? <Loader2 className="animate-spin" /> : <SendHorizontal />}
        </Button>
      </div>
      {(voiceNote || speech.error) && (
        <p role="alert" className="mx-auto mt-1.5 w-full max-w-3xl text-xs text-destructive">
          {voiceNote ?? speech.error}
        </p>
      )}
      <div className="mx-auto mt-1.5 flex w-full max-w-3xl items-center justify-between text-xs text-muted-foreground">
        <span>Enter to send · Shift+Enter for a new line</span>
        <span className={cn("tabular-nums", nearLimit && "font-medium text-destructive")} aria-label="Characters used">
          {text.length}/{maxLength}
        </span>
      </div>
    </form>
  );
}
