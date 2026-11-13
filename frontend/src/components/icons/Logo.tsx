import type { SVGProps } from "react";

/** Interviewra mark: speech bubble with sound bars. Uses currentColor, so it follows the theme's accent color. */
export function Logo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" aria-hidden="true" {...props}>
      <path
        d="M16 8H48A8 8 0 0 1 56 16V38A8 8 0 0 1 48 46H34L22 56V46H16A8 8 0 0 1 8 38V16A8 8 0 0 1 16 8Z"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinejoin="round"
      />
      <g stroke="currentColor" strokeWidth="4" strokeLinecap="round">
        <path d="M20 29V25" />
        <path d="M26 33V21" />
        <path d="M32 36V18" />
        <path d="M38 33V21" />
        <path d="M44 29V25" />
      </g>
    </svg>
  );
}
