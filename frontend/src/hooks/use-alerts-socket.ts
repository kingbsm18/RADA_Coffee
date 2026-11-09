"use client";

import { useEffect, useRef, useState } from "react";

import type { AlertSocketMessage } from "@/lib/api/types";
import { connectAlertsSocket, type SocketState } from "@/lib/realtime/alerts-socket";

/**
 * Live alert stream of one site. `onMessage` is called for every pushed message
 * (alert_created / alert_updated); callers typically refetch. Returns the socket state.
 */
export function useAlertsSocket(siteId: string | null, onMessage: (m: AlertSocketMessage) => void): SocketState {
  const [state, setState] = useState<SocketState>("closed");
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    if (!siteId) return;
    return connectAlertsSocket(siteId, {
      onMessage: (message) => handler.current(message),
      onState: setState,
    });
  }, [siteId]);

  return state;
}
