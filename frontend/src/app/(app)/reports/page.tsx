"use client";

import { SiteRequired } from "@/components/layout/site-required";
import { ReportsView } from "@/components/reports/reports-view";

export default function ReportsPage() {
  return (
    <SiteRequired>
      {(site) => <ReportsView key={site.id} siteId={site.id} currency={site.currency} timezone={site.timezone} />}
    </SiteRequired>
  );
}
