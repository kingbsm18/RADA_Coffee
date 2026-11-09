"use client";

import { CamerasOverview } from "@/components/events/cameras-overview";
import { SiteRequired } from "@/components/layout/site-required";

export default function CamerasPage() {
  return <SiteRequired>{(site) => <CamerasOverview key={site.id} siteId={site.id} />}</SiteRequired>;
}
