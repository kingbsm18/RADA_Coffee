"use client";

import { AlertsReview } from "@/components/alerts/alerts-review";
import { SiteRequired } from "@/components/layout/site-required";

export default function AlertsPage() {
  return <SiteRequired>{(site) => <AlertsReview key={site.id} siteId={site.id} currency={site.currency} />}</SiteRequired>;
}
