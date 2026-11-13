/** Three animated dots (transform + opacity only). */
export function TypingIndicator() {
  return (
    <span role="status" aria-label="Alex is typing" className="inline-flex items-center gap-1.5 py-2">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          aria-hidden
          className="size-2 animate-typing rounded-full bg-muted-foreground"
          style={{ animationDelay: `${i * 160}ms` }}
        />
      ))}
    </span>
  );
}
