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
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardContent className="space-y-4 p-6">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <ScanEye className="h-5 w-5 text-primary" aria-hidden />
            RADA_COFFEE
          </div>
          <div className="space-y-3" role="group" aria-label="Connexion">
            <label className="block space-y-1 text-sm">
              Identifiant
              <Input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
            </label>
            <label className="block space-y-1 text-sm">
              Mot de passe
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && username && password && void submit()}
              />
            </label>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button className="w-full" disabled={busy || !username || !password} onClick={() => void submit()}>
              {busy ? "Connexion…" : "Se connecter"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
