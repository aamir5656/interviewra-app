"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

/** Both icons are in the DOM and swapped with CSS, so there is no hydration flicker. */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle light and dark theme"
      title="Toggle theme"
      onClick={() => setTheme(resolvedTheme === "light" ? "dark" : "light")}
    >
      <Sun className="hidden dark:block" />
      <Moon className="dark:hidden" />
    </Button>
  );
}
