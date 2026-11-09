"use client";

import { ImageOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

interface SnapshotImageProps {
  siteId: string;
  snapshotRef: string | null;
  alt: string;
  className?: string;
}

/**
 * Loads a snapshot with the bearer token (an <img> cannot send headers), lazily: only
 * when the element scrolls into view. The object URL is revoked on unmount.
 */
export function SnapshotImage({ siteId, snapshotRef, alt, className }: SnapshotImageProps) {
  const holder = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const node = holder.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) => entry?.isIntersecting && setVisible(true));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !snapshotRef) return;
    const ctl = new AbortController();
    let objectUrl: string | null = null;
    setFailed(false);
    api
      .snapshotBlob(siteId, snapshotRef, ctl.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => !ctl.signal.aborted && setFailed(true));
    return () => {
      ctl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [visible, siteId, snapshotRef]);

  return (
    <div ref={holder} className={cn("flex items-center justify-center overflow-hidden rounded bg-muted", className)}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- authenticated blob URL, not optimizable
        <img src={src} alt={alt} className="h-full w-full object-cover" />
      ) : (
        <span
          className="flex flex-col items-center gap-1 text-[10px] text-muted-foreground"
          title={!snapshotRef ? "Pas de photo pour cet événement" : failed ? "Photo indisponible" : "Chargement…"}
        >
          <ImageOff className="h-4 w-4" aria-hidden />
          {!snapshotRef ? "Pas de photo" : failed ? "Indisponible" : ""}
        </span>
      )}
    </div>
  );
}
