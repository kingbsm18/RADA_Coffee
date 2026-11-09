import { AppShell } from "@/components/layout/app-shell";
import { SessionProvider } from "@/hooks/use-session";

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
