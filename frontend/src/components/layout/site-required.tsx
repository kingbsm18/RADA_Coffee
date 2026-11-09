"use client";

import { useSession } from "@/hooks/use-session";
import type { SiteOut } from "@/lib/api/types";

/** Renders children with the selected site, or an explicit empty state. */
export function SiteRequired({ children }: { children: (site: SiteOut) => React.ReactNode }) {
  const { site } = useSession();
  if (!site) {
    return (
      <p className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
        Aucun café n&apos;est associé à ce compte.
      </p>
    );
  }
  return <>{children(site)}</>;
}
