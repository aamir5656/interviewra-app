import Link from "next/link";

import { GithubIcon } from "@/components/icons/GithubIcon";
import { buttonVariants } from "@/components/ui/button";
import { GITHUB_URL, SITE_NAME } from "@/lib/site";
import { cn } from "@/lib/utils";

export function Footer() {
  return (
    <footer className="px-4 py-14 sm:px-6">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 text-center">
        <h2 className="text-2xl font-bold sm:text-3xl">Ready for your first practice round?</h2>
        <Link href="/interview/new" className={cn(buttonVariants({ size: "lg" }))}>
          Start Free Mock Interview
        </Link>
        <div className="mt-6 flex w-full flex-col items-center justify-between gap-3 border-t border-border pt-6 text-sm text-muted-foreground sm:flex-row">
          <p>
            © {SITE_NAME}. A portfolio project, free to use.
          </p>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-md transition-colors hover:text-foreground"
          >
            <GithubIcon className="size-4" /> View on GitHub
          </a>
        </div>
      </div>
    </footer>
  );
}
