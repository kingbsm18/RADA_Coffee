"use client";

import { LiveOperations } from "@/components/live/live-operations";
import { SiteRequired } from "@/components/layout/site-required";

export default function LivePage() {
  return (
    <SiteRequired>
      {(site) => <LiveOperations key={site.id} siteId={site.id} currency={site.currency} />}
    </SiteRequired>
  );
}
