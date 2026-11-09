"use client";

import { EventsTable } from "@/components/events/events-table";
import { SiteRequired } from "@/components/layout/site-required";

export default function EventsPage() {
  return <SiteRequired>{(site) => <EventsTable key={site.id} siteId={site.id} />}</SiteRequired>;
}
