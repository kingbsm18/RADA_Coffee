"use client";

import { Camera, Expand, Gauge, ImageDown, VideoOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { DerivedCamera } from "@/lib/domain/cameras";
import { formatTime, relativeAge } from "@/lib/domain/format";
import type { DetectionBox } from "@/lib/streaming/overlay";
import { nextPlayerState, type VideoEventName } from "@/lib/streaming/player-state";
import { PLAYER_STATE_LABEL, resolveStreamSource, type PlayerState } from "@/lib/streaming/source";
import { cn } from "@/lib/utils";

interface CameraPlayerProps {
  siteId: string;
  cameras: DerivedCamera[];
  selectedCameraId: string | null;
  onSelectCamera: (cameraId: string) => void;
  /** Real detection boxes only. Empty today: visual_event.v1 has no bounding box. */
  boxes?: DetectionBox[];
}

const STATE_TONE: Record<PlayerState, "success" | "warning" | "danger" | "neutral"> = {
  live: "success",
  connecting: "warning",
  reconnecting: "warning",
  offline: "danger",
  error: "danger",
  unavailable: "neutral",
};

const VIDEO_EVENTS: VideoEventName[] = ["loadstart", "playing", "waiting", "stalled", "error", "ended", "emptied"];

export function CameraPlayer({ siteId, cameras, selectedCameraId, onSelectCamera, boxes = [] }: CameraPlayerProps) {
  const frame = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const camera = cameras.find((c) => c.cameraId === selectedCameraId) ?? null;
  const source = camera ? resolveStreamSource(siteId, camera.cameraId) : null;

  const [playerState, setPlayerState] = useState<PlayerState>("unavailable");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!source || source.kind === "unavailable") {
      setPlayerState("unavailable");
      return;
    }
    const element = video.current;
    if (!element) return;
    // Only native HLS (Safari) is supported without hls.js; say so instead of failing silently.
    if (!element.canPlayType("application/vnd.apple.mpegurl")) {
      setPlayerState("error");
      return;
    }
    setPlayerState("connecting");
    const listeners = VIDEO_EVENTS.map((name) => {
      const fn = () => setPlayerState((current) => nextPlayerState(current, name));
      element.addEventListener(name, fn);
      return [name, fn] as const;
    });
    element.src = source.url;
    void element.play().catch(() => undefined);
    return () => {
      listeners.forEach(([name, fn]) => element.removeEventListener(name, fn));
      element.removeAttribute("src");
      element.load();
    };
  }, [source, attempt]);

  const fullscreen = useCallback(() => {
    void frame.current?.requestFullscreen?.();
  }, []);

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center gap-2">
        <Select value={selectedCameraId ?? ""} onValueChange={onSelectCamera} disabled={cameras.length === 0}>
          <SelectTrigger aria-label="Caméra" className="w-56">
            <SelectValue placeholder="Aucune caméra détectée" />
          </SelectTrigger>
          <SelectContent>
            {cameras.map((c) => (
              <SelectItem key={c.cameraId} value={c.cameraId}>
                {c.cameraId}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Badge tone={STATE_TONE[playerState]} data-testid="player-state">
          {PLAYER_STATE_LABEL[playerState]}
        </Badge>
        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            disabled
            title="Capture d'image non disponible : aucun flux live n'est branché"
            aria-label="Capture d'image (indisponible)"
          >
            <ImageDown className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={fullscreen} title="Plein écran" aria-label="Plein écran">
            <Expand className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div
        ref={frame}
        className="relative aspect-video w-full overflow-hidden rounded-lg border bg-black"
        data-testid="player-frame"
      >
        <video ref={video} className={cn("h-full w-full object-contain", source?.kind !== "hls" && "hidden")} muted playsInline />

        {boxes.map((box) => (
          <div
            key={box.eventId}
            className="absolute border-2 border-primary"
            style={{
              left: `${box.x * 100}%`,
              top: `${box.y * 100}%`,
              width: `${box.width * 100}%`,
              height: `${box.height * 100}%`,
            }}
          >
            <span className="absolute -top-5 left-0 whitespace-nowrap bg-primary px-1 text-[10px] text-primary-foreground">
              {box.label} {Math.round(box.confidence * 100)} % · {formatTime(box.timestamp)}
            </span>
          </div>
        ))}

        {(playerState === "unavailable" || playerState === "error") && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            {camera ? <VideoOff className="h-10 w-10 text-muted-foreground" aria-hidden /> : <Camera className="h-10 w-10 text-muted-foreground" aria-hidden />}
            <p className="text-sm font-medium">
              {!camera
                ? "Aucune caméra n'a encore envoyé d'événement."
                : playerState === "error"
                  ? "Ce navigateur ne peut pas lire le flux HLS sans lecteur dédié."
                  : "Flux vidéo en direct indisponible"}
            </p>
            {camera && source?.kind === "unavailable" && (
              <p className="max-w-md text-xs text-muted-foreground">
                {source.detail} Les événements de détection et le rapprochement caisse restent actifs ci-contre.
              </p>
            )}
            {playerState === "error" && (
              <Button size="sm" variant="outline" onClick={() => setAttempt((n) => n + 1)}>
                Réessayer
              </Button>
            )}
          </div>
        )}
        {(playerState === "connecting" || playerState === "reconnecting") && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-sm">
            {PLAYER_STATE_LABEL[playerState]}
          </div>
        )}
      </div>

      <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <div className="flex gap-1">
          <dt>Caméra</dt>
          <dd className="text-foreground">{camera?.cameraId ?? "—"}</dd>
        </div>
        <div className="flex gap-1" title="Dernier événement de détection reçu de cette caméra (pas la dernière image du flux)">
          <dt>Dernier événement</dt>
          <dd className="text-foreground">{camera ? `${formatTime(camera.lastEventAt)} (${relativeAge(camera.lastEventAt)})` : "—"}</dd>
        </div>
        <div className="flex items-center gap-1" title="Non fourni par le backend : aucun flux live n'est branché">
          <Gauge className="h-3 w-3" aria-hidden />
          <dt>FPS / latence</dt>
          <dd className="text-foreground">n/d</dd>
        </div>
      </dl>
    </div>
  );
}
