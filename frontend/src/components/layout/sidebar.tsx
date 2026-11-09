"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ScanEye } from "lucide-react";

import { NAV_ITEMS } from "@/components/layout/nav";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav aria-label="Navigation principale" className="flex w-14 shrink-0 flex-col gap-1 border-r border-[#142B4D] bg-[#07152B] p-2 text-slate-400 lg:w-60 lg:p-3">
      <Link href="/live" className="mb-5 flex items-center gap-2 rounded-lg px-2 py-1.5 text-white" aria-label="RADA Coffee accueil">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500/15 text-purple-300">
          <ScanEye className="h-4 w-4" aria-hidden />
        </span>
        <span className="hidden lg:block">
          <span className="block text-sm font-semibold tracking-[0.18em]">RADA</span>
          <span className="block text-[9px] font-medium tracking-[0.18em] text-slate-500">COFFEE INTELLIGENCE</span>
        </span>
      </Link>
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            title={label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm text-slate-400 transition-colors hover:bg-white/10 hover:text-white",
              active && "bg-purple-500/15 font-medium text-white", 
            )}
          >
            <Icon className={cn("h-4 w-4 shrink-0", active && "text-primary")} />
            <span className="hidden lg:inline">{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
