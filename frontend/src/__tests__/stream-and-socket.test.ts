import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setToken, clearSession } from "@/lib/auth";
import { connectAlertsSocket } from "@/lib/realtime/alerts-socket";
import { resolveStreamSource } from "@/lib/streaming/source";

describe("stream source boundary", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("never fakes a stream when no gateway is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_STREAM_GATEWAY_URL", "");
    const source = resolveStreamSource("site", "cam-1");
    expect(source.kind).toBe("unavailable");
    if (source.kind === "unavailable") expect(source.reason).toBe("no_gateway_configured");
  });

  it("with a gateway URL but no backend stream endpoint: still unavailable, never built from RTSP", () => {
    vi.stubEnv("NEXT_PUBLIC_STREAM_GATEWAY_URL", "https://stream.example.com");
    const source = resolveStreamSource("site", "cam-1");
    expect(source.kind).toBe("unavailable");
    expect(JSON.stringify(source)).not.toMatch(/rtsp/i);
  });
});

class FakeSocket {
  static instances: FakeSocket[] = [];
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.({ code: 1000 });
  }
}

describe("alerts socket", () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.useFakeTimers();
    setToken("secret-token");
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    clearSession();
  });

  it("sends the token as the first message, never in the URL", () => {
    const states: string[] = [];
    connectAlertsSocket("cafe-1", { onMessage: () => undefined, onState: (s) => states.push(s) });
    const ws = FakeSocket.instances[0]!;
    expect(ws.url).toContain("/ws/alerts?site_id=cafe-1");
    expect(ws.url).not.toContain("secret-token");
    ws.onopen?.();
    expect(JSON.parse(ws.sent[0]!)).toEqual({ token: "secret-token" });
    ws.onmessage?.({ data: JSON.stringify({ type: "ready" }) });
    expect(states).toContain("open");
  });

  it("reconnects with backoff after an unexpected close", () => {
    connectAlertsSocket("cafe-1", { onMessage: () => undefined, onState: () => undefined });
    FakeSocket.instances[0]!.onclose?.({ code: 1006 });
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("does not retry after a policy violation (refused token/site)", () => {
    const states: string[] = [];
    connectAlertsSocket("cafe-1", { onMessage: () => undefined, onState: (s) => states.push(s) });
    FakeSocket.instances[0]!.onclose?.({ code: 1008 });
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(states.at(-1)).toBe("closed");
  });

  it("stops reconnecting once unsubscribed", () => {
    const stop = connectAlertsSocket("cafe-1", { onMessage: () => undefined, onState: () => undefined });
    stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
