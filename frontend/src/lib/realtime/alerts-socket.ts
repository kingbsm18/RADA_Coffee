import { getToken } from "@/lib/auth";
import { wsUrl } from "@/lib/config";
import type { AlertSocketMessage } from "@/lib/api/types";

export type SocketState = "connecting" | "open" | "reconnecting" | "closed";

export interface AlertsSocketHandlers {
  onMessage: (message: AlertSocketMessage) => void;
  onState: (state: SocketState) => void;
}

const BACKOFF_MS = [1_000, 2_000, 5_000, 10_000, 30_000];
const POLICY_VIOLATION = 1008;

/**
 * Subscribes to /ws/alerts for one site. The backend expects the token as the FIRST
 * message (never in the URL) and answers {"type": "ready"}. Reconnects with backoff.
 * Returns an unsubscribe function.
 */
export function connectAlertsSocket(siteId: string, handlers: AlertsSocketHandlers): () => void {
  let socket: WebSocket | null = null;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const open = () => {
    handlers.onState(attempt === 0 ? "connecting" : "reconnecting");
    const ws = new WebSocket(`${wsUrl("/ws/alerts")}?site_id=${encodeURIComponent(siteId)}`);
    socket = ws;

    ws.onopen = () => {
      const token = getToken();
      if (!token) {
        ws.close();
        return;
      }
      ws.send(JSON.stringify({ token }));
    };
    ws.onmessage = (event: MessageEvent<string>) => {
      let message: AlertSocketMessage;
      try {
        message = JSON.parse(event.data) as AlertSocketMessage;
      } catch {
        return;
      }
      if (message.type === "ready") {
        attempt = 0;
        handlers.onState("open");
      }
      handlers.onMessage(message);
    };
    ws.onclose = (event) => {
      if (stopped) return;
      if (event.code === POLICY_VIOLATION) {
        handlers.onState("closed"); // refused (expired token / wrong site): do not hammer the server
        return;
      }
      handlers.onState("reconnecting");
      const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 30_000;
      attempt += 1;
      timer = setTimeout(open, delay);
    };
  };

  open();

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    socket?.close();
    handlers.onState("closed");
  };
}
