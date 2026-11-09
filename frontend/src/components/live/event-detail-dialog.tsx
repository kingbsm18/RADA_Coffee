"use client";

import Link from "next/link";

import { CategoryPhotos } from "@/components/live/category-photos";
import { EventStateBadge } from "@/components/live/event-state-badge";
import { SnapshotImage } from "@/components/live/snapshot-image";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { displayQty, quantityView, type LiveEventRow } from "@/lib/domain/events";
import { formatConfidence, formatDateTime, formatMoney } from "@/lib/domain/format";
import { alertStatusLabel, alertStatusTone } from "@/lib/domain/labels";

interface EventDetailDialogProps {
  siteId: string;
  currency: string;
  row: LiveEventRow | null;
  onClose: () => void;
}

export function EventDetailDialog({ siteId, currency, row, onClose }: EventDetailDialogProps) {
  return (
    <Dialog open={row !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>{row && <Body siteId={siteId} currency={currency} row={row} />}</DialogContent>
    </Dialog>
  );
}

function Body({ siteId, currency, row }: { siteId: string; currency: string; row: LiveEventRow }) {
  const { event, alert } = row;
  const qty = quantityView(row);

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {event.category} ×{event.count} — {formatDateTime(event.timestamp)}
        </DialogTitle>
        <DialogDescription>
          Un écart est un signal à vérifier, pas une preuve. Une photo isolée ne prouve rien.
        </DialogDescription>
      </DialogHeader>

      <SnapshotImage siteId={siteId} snapshotRef={event.snapshot_ref} alt={`Photo ${event.category}`} className="aspect-video w-full" />

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <Field label="Statut">
          <EventStateBadge state={event.state} />
        </Field>
        <Field label="Caméra">{event.camera_id}</Field>
        <Field label="Confiance">{formatConfidence(event.confidence)}</Field>
        <Field label="Quantité détectée">{event.count}</Field>
        <Field label="Rapprochée (caisse)">{displayQty(qty.matched)}</Field>
        <Field label="Écart à vérifier">{displayQty(qty.unmatched)}</Field>
        <Field label="Modèle">{event.model_version}</Field>
      </dl>

      {alert && (
        <div className="space-y-2 rounded-md border p-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="font-medium">Alerte</span>
            <Badge tone={alertStatusTone(alert.status)}>{alertStatusLabel(alert.status)}</Badge>
          </div>
          <p>
            Perte estimée :{" "}
            <strong>{formatMoney(alert.loss_est, currency)}</strong>{" "}
            <span className="text-muted-foreground">
              (fourchette {formatMoney(alert.loss_min, currency)} – {formatMoney(alert.loss_max, currency)})
            </span>
          </p>
          <Link href="/alerts" className="text-primary underline-offset-2 hover:underline">
            Examiner dans Alerts &amp; Review
          </Link>
        </div>
      )}

      <CategoryPhotos siteId={siteId} category={event.category} around={event.timestamp} windowMinutes={15} />
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
