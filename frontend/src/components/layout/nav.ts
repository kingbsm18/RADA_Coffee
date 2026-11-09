import { Bell, BarChart3, Camera, FileText, ListVideo, Settings, Video, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/live", label: "Live Operations", icon: Video },
  { href: "/cameras", label: "Cameras", icon: Camera },
  { href: "/events", label: "Events", icon: ListVideo },
  { href: "/revenue", label: "Revenue Intelligence", icon: BarChart3 },
  { href: "/alerts", label: "Alerts & Review", icon: Bell },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
];
