"use client";

import { SiteRequired } from "@/components/layout/site-required";
import { RevenueIntelligence } from "@/components/revenue/revenue-intelligence";

export default function RevenuePage() {
  return (
    <SiteRequired>
      {(site) => <RevenueIntelligence key={site.id} siteId={site.id} currency={site.currency} timezone={site.timezone} />}
    </SiteRequired>
  );
}
