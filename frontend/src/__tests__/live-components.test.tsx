import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CameraPlayer } from "@/components/live/camera-player";
import { LiveEventFeed } from "@/components/live/live-event-feed";
import { buildStatusItems, OperationalStatusBar } from "@/components/live/operational-status-bar";
import type { AlertOut, EventOut } from "@/lib/api/types";
import { joinEventsWithAlerts } from "@/lib/domain/events";

const ev = (over: Partial<EventOut>): EventOut => ({
  id: "d1",
  event_id: "e1",
  site_id: "s",
  camera_id: "cam-1",
  timestamp: "2026-11-08T10:00:00Z",
  category: "coffee",
  count: 3,
  confidence: 0.91,
  snapshot_ref: null,
  model_version: "m",
  state: "anomaly",
  ...over,
});

const al: AlertOut = {
  id: "a1",
  site_id: "s",
  detection_id: "d1",
  category: "coffee",
  subtype: null,
  missing_qty: 2,
  loss_est: "30.00",
  loss_min: "25.00",
  loss_max: "35.00",
  status: "open",
  strong: false,
  review_note: null,
  created_at: "2026-11-08T10:20:00Z",
  resolved_at: null,
};

describe("LiveEventFeed", () => {
  it("shows category, quantity, confidence, status and unmatched quantity", () => {
    const rows = joinEventsWithAlerts([ev({})], [al]);
    render(<LiveEventFeed siteId="s" rows={rows} loading={false} error={null} selectedEventId={null} onSelect={() => undefined} />);
    const item = within(screen.getByTestId("event-feed")).getByRole("button");
    expect(item).toHaveTextContent("coffee");
    expect(item).toHaveTextContent("×3");
    expect(item).toHaveTextContent("Confiance 91 %");
    expect(item).toHaveTextContent("Écart à vérifier");
    expect(item).toHaveTextContent("Écart 2");
    expect(item).toHaveTextContent("Rapprochée —");
  });

  it("calls onSelect with the row when clicked", async () => {
    const onSelect = vi.fn();
    const rows = joinEventsWithAlerts([ev({})], []);
    render(<LiveEventFeed siteId="s" rows={rows} loading={false} error={null} selectedEventId={null} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith(rows[0]);
  });

  it("shows an empty state and an error without crashing", () => {
    const { rerender } = render(
      <LiveEventFeed siteId="s" rows={[]} loading={false} error={null} selectedEventId={null} onSelect={() => undefined} />,
    );
    expect(screen.getByText("Aucun événement pour le moment.")).toBeInTheDocument();
    rerender(<LiveEventFeed siteId="s" rows={[]} loading={false} error="Serveur injoignable" selectedEventId={null} onSelect={() => undefined} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Serveur injoignable");
  });
});

describe("CameraPlayer without a stream gateway", () => {
  it("says the stream is unavailable and does not pretend to be live", () => {
    render(
      <CameraPlayer
        siteId="s"
        cameras={[{ cameraId: "cam-1", lastEventAt: "2026-11-08T10:00:00Z", eventCount: 4 }]}
        selectedCameraId="cam-1"
        onSelectCamera={() => undefined}
      />,
    );
    expect(screen.getByTestId("player-state")).toHaveTextContent("Flux indisponible");
    expect(screen.getByText("Flux vidéo en direct indisponible")).toBeInTheDocument();
    expect(screen.queryByText("En direct")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Capture d'image (indisponible)")).toBeDisabled();
  });

  it("explains when no camera has reported yet", () => {
    render(<CameraPlayer siteId="s" cameras={[]} selectedCameraId={null} onSelectCamera={() => undefined} />);
    expect(screen.getByText("Aucune caméra n'a encore envoyé d'événement.")).toBeInTheDocument();
  });

  it("draws no detection box when none is provided", () => {
    const { container } = render(
      <CameraPlayer siteId="s" cameras={[]} selectedCameraId={null} onSelectCamera={() => undefined} />,
    );
    expect(container.querySelectorAll(".border-primary")).toHaveLength(0);
  });
});

describe("OperationalStatusBar", () => {
  it("marks backend-unknown values as n/d instead of inventing them", () => {
    const items = buildStatusItems({ apiReady: true, socket: "open", lastEventAt: null, lastPosSyncAt: null, posSyncKnown: true });
    render(<OperationalStatusBar items={items} />);
    const edge = screen.getByText("Appareil edge").closest("li")!;
    expect(edge).toHaveTextContent("n/d");
    const detection = screen.getByText("Traitement des détections").closest("li")!;
    expect(detection).toHaveTextContent("n/d");
    expect(screen.getByText("API backend").closest("li")).toHaveTextContent("Opérationnelle");
    expect(screen.getByText("Dernière synchro POS").closest("li")).toHaveTextContent("aucune");
  });
});
