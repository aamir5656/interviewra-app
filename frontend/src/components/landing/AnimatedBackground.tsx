/** Soft lime glow plus a faint grid. The glow only moves with transform (CSS keyframes); reduced motion stops it. */
export function AnimatedBackground() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div
        className="absolute inset-0 opacity-[0.35] [mask-image:radial-gradient(ellipse_at_50%_20%,black,transparent_70%)]"
        style={{
          backgroundImage:
            "linear-gradient(to right, var(--border) 1px, transparent 1px), linear-gradient(to bottom, var(--border) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }}
      />
      <div
        className="absolute -top-40 left-1/2 h-[34rem] w-[34rem] -translate-x-[75%] animate-drift rounded-full opacity-25 will-change-transform"
        style={{ background: "radial-gradient(closest-side, var(--accent), transparent)" }}
      />
      <div
        className="absolute top-24 left-1/2 h-[28rem] w-[28rem] translate-x-[10%] animate-drift-slow rounded-full opacity-20 will-change-transform"
        style={{ background: "radial-gradient(closest-side, var(--accent-2), transparent)" }}
      />
    </div>
  );
}
