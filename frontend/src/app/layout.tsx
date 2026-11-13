import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import type { ReactNode } from "react";

import { Header } from "@/components/layout/Header";
import { ServerStatusBanner } from "@/components/layout/ServerStatusBanner";
import { Providers } from "@/components/providers/Providers";
import "@/styles/globals.css";

const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Interviewra: AI mock interview coach",
  description: "Practice real interviews with an AI interviewer and get a detailed, honest report. Free, no signup.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${spaceGrotesk.variable} ${inter.variable}`}>
      <body className="min-h-dvh antialiased">
        <Providers>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
          >
            Skip to content
          </a>
          <div className="flex min-h-dvh flex-col">
            <Header />
            <ServerStatusBanner />
            <main id="main" className="flex-1">
              {children}
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
