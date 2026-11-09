import type { PlayerState } from "@/lib/streaming/source";

/** HTMLVideoElement events that change what the operator sees. */
export type VideoEventName = "loadstart" | "playing" | "waiting" | "stalled" | "error" | "ended" | "emptied";

/** Pure state machine for the player status badge (unit-tested). */
export function nextPlayerState(current: PlayerState, event: VideoEventName): PlayerState {
  switch (event) {
    case "loadstart":
      return current === "live" ? "reconnecting" : "connecting";
    case "playing":
      return "live";
    case "waiting":
    case "stalled":
      return current === "live" || current === "reconnecting" ? "reconnecting" : current;
    case "error":
      return "error";
    case "ended":
    case "emptied":
      return "offline";
    default:
      return current;
  }
}
