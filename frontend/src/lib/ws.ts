// Live alert stream. The token is sent as the FIRST message (never in the URL: URLs get logged).
import { API_URL, type Alert, getToken } from "./api";

export type AlertEvent = { type: "alert_created" | "alert_updated"; alert: Partial<Alert> & { id: string } };
type Message = AlertEvent | { type: "ready" };

const POLICY_VIOLATION = 1008; // the backend refused the token or the site
const MAX_BACKOFF_MS = 30_000;

export function connectAlerts(
  siteId: string,
  onEvent: (event: AlertEvent) => void,
  onStatus: (status: "connecting" | "live" | "closed" | "unauthorized") => void = () => {},
): () => void {
  let socket: WebSocket | null = null;
  let attempt = 0;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const open = () => {
    onStatus("connecting");
    const url = new URL("/api/v1/ws/alerts", API_URL);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("site_id", siteId);
    const ws = new WebSocket(url.toString());
    socket = ws;

    ws.onopen = () => ws.send(JSON.stringify({ token: getToken() }));
    ws.onmessage = (message) => {
      const data = JSON.parse(String(message.data)) as Message;
      if (data.type === "ready") {
        attempt = 0;
        onStatus("live");
      } else {
        onEvent(data);
      }
    };
    ws.onclose = (closeEvent) => {
      if (stopped) return;
      if (closeEvent.code === POLICY_VIOLATION) {
        onStatus("unauthorized"); // log in again; retrying with the same token is pointless
        return;
      }
      onStatus("closed");
      const delay = Math.min(1000 * 2 ** attempt++, MAX_BACKOFF_MS);
      timer = setTimeout(open, delay);
    };
  };

  open();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    socket?.close();
  };
}
