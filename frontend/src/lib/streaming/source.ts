/**
 * Stream integration boundary.
 *
 * Intended architecture:  CCTV -> RADA Edge -> Secure Stream Gateway -> Browser player.
 * The edge only reads RTSP (edge/video/capture.py); nothing in the repository serves
 * HLS, WebRTC or MJPEG yet, and no backend endpoint hands out a stream URL. Therefore
 * resolveStreamSource() cannot return a playable source today and says why. It never
 * invents a URL and never builds one from an RTSP address or credentials.
 *
 * When the gateway exists, only this file changes: return { kind: "hls", url } (or add a
 * "webrtc" kind) from a short-lived, authenticated URL issued by the backend.
 * See docs/frontend_streaming.md for the required contract.
 */
import { streamGatewayUrl } from "@/lib/config";

export type StreamSource =
  | { kind: "hls"; url: string }
  | { kind: "unavailable"; reason: StreamUnavailableReason; detail: string };

export type StreamUnavailableReason = "no_gateway_configured" | "no_stream_endpoint";

export function resolveStreamSource(_siteId: string, _cameraId: string): StreamSource {
  if (!streamGatewayUrl()) {
    return {
      kind: "unavailable",
      reason: "no_gateway_configured",
      detail: "Aucune passerelle de flux n'est configurée (NEXT_PUBLIC_STREAM_GATEWAY_URL).",
    };
  }
  return {
    kind: "unavailable",
    reason: "no_stream_endpoint",
    detail:
      "Une passerelle est configurée, mais le backend n'expose pas encore d'endpoint délivrant une URL de flux authentifiée pour une caméra.",
  };
}

export type PlayerState = "connecting" | "live" | "reconnecting" | "offline" | "error" | "unavailable";

export const PLAYER_STATE_LABEL: Record<PlayerState, string> = {
  connecting: "Connexion…",
  live: "En direct",
  reconnecting: "Reconnexion…",
  offline: "Hors ligne",
  error: "Erreur de flux",
  unavailable: "Flux indisponible",
};
