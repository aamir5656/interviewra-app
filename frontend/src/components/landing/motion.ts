/** Shared motion settings. Every animation is 150-400 ms and uses only transform and opacity. */
export const EASE = [0.22, 1, 0.36, 1] as const;
export const DURATION = { fast: 0.2, base: 0.32, slow: 0.4 } as const;
export const VIEWPORT = { once: true, margin: "-60px" } as const;
