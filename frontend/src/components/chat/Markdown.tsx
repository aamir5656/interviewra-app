import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/** Interviewer text: markdown inside a typography container themed with the page's color tokens. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none leading-relaxed break-words",
        "[--tw-prose-body:var(--text)] [--tw-prose-headings:var(--text)] [--tw-prose-bold:var(--text)] [--tw-prose-links:var(--accent)]",
        "[--tw-prose-bullets:var(--muted)] [--tw-prose-counters:var(--muted)] [--tw-prose-code:var(--text)] [--tw-prose-quotes:var(--text)]",
        "[--tw-prose-hr:var(--border)] [--tw-prose-th-borders:var(--border)] [--tw-prose-td-borders:var(--border)] [--tw-prose-pre-bg:var(--bg)]",
        "prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-strong:font-semibold prose-headings:my-2 [&>:first-child]:mt-0 [&>:last-child]:mb-0",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          img: () => null, // the interviewer never needs images
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
