"use client";

import { SiteRequired } from "@/components/layout/site-required";
import { SettingsView } from "@/components/settings/settings-view";

export default function SettingsPage() {
  return <SiteRequired>{(site) => <SettingsView key={site.id} site={site} />}</SiteRequired>;
}
