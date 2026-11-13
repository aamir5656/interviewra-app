"use client";

import type { ReactNode } from "react";
import { ThemeProvider, useTheme } from "next-themes";
import { Toaster } from "sonner";

import { GuestProvider } from "@/components/providers/GuestProvider";

function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  return <Toaster position="top-center" theme={resolvedTheme === "light" ? "light" : "dark"} richColors closeButton />;
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
      <GuestProvider>
        {children}
        <ThemedToaster />
      </GuestProvider>
    </ThemeProvider>
  );
}
