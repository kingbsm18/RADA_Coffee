"use client";

import { useCallback } from "react";

import { ErrorBanner, MissingBackend, PageHeader } from "@/components/page-header";
import { usePolling } from "@/hooks/use-polling";
import type { SiteOut } from "@/lib/api/types";
import { api } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/domain/format";

const UPLOAD_POLICY_LABEL: Record<string, string> = {
  always: "Toujours",
  on_alert: "Sur alerte uniquement",
  never: "Jamais",
};

export function SettingsView({ site }: { site: SiteOut }) {
  const fetchSettings = useCallback(() => api.siteSettings(site.id), [site.id]);
  const settings = usePolling(fetchSettings, 120_000);
  const s = settings.data;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Configuration du café telle qu'enregistrée sur le serveur (lecture seule)."
      />
      {settings.error && <ErrorBanner message={settings.error} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border bg-card p-4" aria-label="Café">
          <h2 className="mb-3 text-sm font-semibold">Café</h2>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-muted-foreground">Nom</dt>
            <dd>{site.name}</dd>
            <dt className="text-muted-foreground">Identifiant</dt>
            <dd className="font-mono text-xs">{site.id}</dd>
            <dt className="text-muted-foreground">Fuseau horaire</dt>
            <dd>{site.timezone}</dd>
            <dt className="text-muted-foreground">Devise</dt>
            <dd>{site.currency}</dd>
          </dl>
        </section>

        {s && (
          <section className="rounded-lg border bg-card p-4" aria-label="Détection">
            <h2 className="mb-3 text-sm font-semibold">Détection et photos</h2>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt className="text-muted-foreground">Seuil de confiance</dt>
              <dd>{Math.round(s.confidence_threshold * 100)} %</dd>
              <dt className="text-muted-foreground">Conservation des photos</dt>
              <dd>{s.snapshot_retention_days} jours</dd>
              <dt className="text-muted-foreground">Envoi des photos</dt>
              <dd>{UPLOAD_POLICY_LABEL[s.snapshot_upload_policy] ?? s.snapshot_upload_policy}</dd>
              <dt className="text-muted-foreground">Mis à jour</dt>
              <dd>{formatDateTime(s.updated_at, site.timezone)}</dd>
            </dl>
          </section>
        )}

        {s && (
          <section className="rounded-lg border bg-card p-4 lg:col-span-2" aria-label="Fenêtres">
            <h2 className="mb-3 text-sm font-semibold">Fenêtres de rapprochement par catégorie</h2>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-1">Catégorie</th>
                  <th className="py-1 text-right">Avant (min)</th>
                  <th className="py-1 text-right">Après / grâce (min)</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {Object.entries(s.windows)
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([category, w]) => (
                    <tr key={category}>
                      <td className="py-1.5 font-medium">{category}</td>
                      <td className="py-1.5 text-right tabular-nums">{w.lookback}</td>
                      <td className="py-1.5 text-right tabular-nums">{w.grace}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </section>
        )}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <MissingBackend title="Modification des réglages">
          La modification (PUT /sites/{"{id}"}/settings) existe côté serveur mais n&apos;est pas encore exposée ici : elle sera ajoutée avec
          confirmation et gestion des rôles.
        </MissingBackend>
        <MissingBackend title="Caméras, POS, notifications, rôles utilisateurs">
          Aucun endpoint de lecture ou de configuration n&apos;existe pour ces éléments (caméras, connecteur POS, canaux de notification, gestion des
          utilisateurs).
        </MissingBackend>
      </div>
    </>
  );
}
