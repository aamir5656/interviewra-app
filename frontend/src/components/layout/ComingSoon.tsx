import { Hammer } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

/** Temporary page body for routes that a later part builds. */
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-24 text-center">
      <Hammer className="size-8 text-brand" aria-hidden />
      <h1 className="text-3xl font-bold">{title}</h1>
      <p className="text-muted-foreground">This page is built in a later part of the project.</p>
      <Link href="/" className={buttonVariants({ variant: "outline" })}>
        Back to home
      </Link>
    </div>
  );
}
