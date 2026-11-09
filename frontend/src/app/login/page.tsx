"use client";

import { ScanEye } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { setToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const token = await api.login(username, password);
      setToken(token.access_token);
      router.replace("/live");
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 429
          ? "Trop de tentatives. Réessayez dans quelques minutes."
          : e instanceof ApiError && e.status === 401
            ? "Identifiant ou mot de passe incorrect."
            : e instanceof Error
              ? e.message
              : "Erreur inconnue",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-muted/30 p-4">
      <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-primary/10 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -bottom-32 -right-20 h-80 w-80 rounded-full bg-primary/10 blur-3xl" aria-hidden />
      <Card className="relative w-full max-w-md border-border/70 bg-card/95 shadow-xl shadow-primary/5 backdrop-blur">
        <CardContent className="space-y-7 p-7 sm:p-9">
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-lg font-semibold tracking-tight">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <ScanEye className="h-5 w-5" aria-hidden />
              </span>
              RADA<span className="text-primary">_COFFEE</span>
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Bienvenue sur votre espace opérations</h1>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Surveillez vos caméras et réconciliez chaque service avec votre caisse.
              </p>
            </div>
          </div>
          <div className="space-y-4" role="group" aria-label="Connexion">
            <label className="block space-y-2 text-sm font-medium">
              Identifiant
              <Input className="h-11" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
            </label>
            <label className="block space-y-2 text-sm font-medium">
              Mot de passe
              <Input
                className="h-11"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.nativeEvent.isComposing || e.keyCode === 229) return;
                  if (e.key === "Enter" && username && password) void submit();
                }}
              />
            </label>
            {error && (
              <p role="alert" className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}
            <Button className="h-11 w-full" disabled={busy || !username || !password} onClick={() => void submit()}>
              {busy ? "Connexion…" : "Se connecter"}
            </Button>
          </div>
          <p className="text-center text-xs text-muted-foreground">Accès sécurisé pour les équipes RADA AI</p>
        </CardContent>
      </Card>
    </main>
  );
}
