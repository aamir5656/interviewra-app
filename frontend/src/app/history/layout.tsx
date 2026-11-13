import { Suspense, type ReactNode } from "react";

import { SidebarShell } from "@/components/layout/SidebarShell";

export default function Layout({ children }: { children: ReactNode }) {
  // usePathname() in the sidebar is runtime data, so it has to sit inside <Suspense> (cacheComponents)
  return (
    <Suspense fallback={null}>
      <SidebarShell>{children}</SidebarShell>
    </Suspense>
  );
}
