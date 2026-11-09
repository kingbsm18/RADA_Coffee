"use client";

import type { SocketState } from "@/lib/realtime/alerts-socket";
import { formatDateTime, relativeAge } from "@/lib/domain/format";

export type Health = "ok" | "warn" | "down" | "unknown";

export interface StatusItem {
  label: string;
  value: string;
  health: Health;
  /** Why the value is what it is (shown on hover); required for "unknown". */
  hint: string;
}

const DOT: Record<Health, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  down: "bg-destructive",
  unknown: "bg-muted-foreground/50",
};

const SOCKET_LABEL: Record<SocketState, { value: string; health: Health }> = {
  open: { value: "Connecté", health: "ok" },
  connecting: { value: "Connexion…", health: "warn" },
  reconnecting: { value: "Reconnexion…", health: "warn" },
  closed: { value: "Déconnecté", health: "down" },
};

export interface StatusInputs {
  apiReady: boolean | null;
  socket: SocketState;
  lastEventAt: string | null;
  lastPosSyncAt: string | null;
  posSyncKnown: boolean;
}

/** Only real backend values; anything the backend cannot tell us is shown as "n/d". */
export function buildStatusItems(input: StatusInputs): StatusItem[] {
  const socket = SOCKET_LABEL[input.socket];
  return [
    {
      label: "API backend",
      value: input.apiReady === null ? "…" : input.apiReady ? "Opérationnelle" : "Indisponible",
      health: input.apiReady === null ? "unknown" : input.apiReady ? "ok" : "down",
      hint: "GET /health/ready",
    },
    {
      label: "Alertes temps réel",
      value: socket.value,
      health: socket.health,
      hint: "WebSocket /ws/alerts",
    },
    {
      label: "Dernier événement caméra",
      value: input.lastEventAt ? relativeAge(input.lastEventAt) : "aucun",
      health: input.lastEventAt ? "ok" : "unknown",
      hint: "Horodatage du dernier événement de détection reçu. Pas un test de connectivité caméra.",
    },
    {
      label: "Dernière synchro POS",
      value: !input.posSyncKnown ? "…" : input.lastPosSyncAt ? formatDateTime(input.lastPosSyncAt) : "aucune",
      health: input.lastPosSyncAt ? "ok" : "unknown",
      hint: "Dernier import POS terminé (GET /sites/{id}/pos/imports).",
    },
    {
      label: "Appareil edge",
      value: "n/d",
      health: "unknown",
      hint: "Le backend n'expose pas encore l'état de l'appareil edge (aucun endpoint heartbeat).",
    },
    {
      label: "Traitement des détections",
      value: "n/d",
      health: "unknown",
      hint: "Le backend n'expose pas encore l'état du traitement des détections.",
    },
  ];
}

export function OperationalStatusBar({ items }: { items: StatusItem[] }) {
  return (
    <ul aria-label="État opérationnel" className="flex flex-wrap gap-x-6 gap-y-1 rounded-lg border bg-card px-3 py-2 text-xs">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5" title={item.hint}>
          <span className={`h-2 w-2 rounded-full ${DOT[item.health]}`} aria-hidden />
          <span className="text-muted-foreground">{item.label}</span>
          <span className="font-medium">{item.value}</span>
        </li>
      ))}
    </ul>
  );
}
