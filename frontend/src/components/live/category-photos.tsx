"use client";

import { useCallback } from "react";

import { SnapshotImage } from "@/components/live/snapshot-image";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/endpoints";
import { formatTime } from "@/lib/domain/format";

interface CategoryPhotosProps {
  siteId: string;
  category: string;
  /** Center of the period (ISO). */
  around: string;
  windowMinutes: number;
}

/** R11: all photos of a category over a period. Never one photo presented as THE proof. */
export function CategoryPhotos({ siteId, category, around, windowMinutes }: CategoryPhotosProps) {
  const fetchPhotos = useCallback(() => {
    const t = new Date(around).getTime();
    const delta = windowMinutes * 60_000;
    return api.listSnapshots(siteId, category, new Date(t - delta).toISOString(), new Date(t + delta).toISOString(), 12);
  }, [siteId, category, around, windowMinutes]);
  const photos = usePolling(fetchPhotos, 3_600_000);

  return (
    <section aria-label="Photos de la même catégorie">
      <h3 className="mb-2 text-sm font-medium">
        Photos « {category} » à ±{windowMinutes} min {photos.data ? `(${photos.data.length})` : ""}
      </h3>
      {photos.error && <p className="text-xs text-destructive">Photos indisponibles : {photos.error}</p>}
      {photos.data && photos.data.length === 0 && (
        <p className="text-xs text-muted-foreground">Aucune photo sur cette période.</p>
      )}
      <ul className="grid grid-cols-4 gap-2 sm:grid-cols-6">
        {photos.data?.map((item) => (
          <li key={item.event_id} className="space-y-1">
            <SnapshotImage
              siteId={siteId}
              snapshotRef={item.url.split(`/images/${siteId}/`)[1] ?? null}
              alt={`Photo ${item.category} ${formatTime(item.timestamp)}`}
              className="aspect-video w-full"
            />
            <span className="block text-center text-[10px] text-muted-foreground">{formatTime(item.timestamp)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
