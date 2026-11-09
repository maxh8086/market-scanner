import { Profiler, type ProfilerOnRenderCallback } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Row } from "../api/results";
import { ScreenerTable } from "./ScreenerTable";

const RUN_ID = "2026-11-09";
const ROW_COUNT = 5000;
const TICKS = 60;
const TICK_FRACTION = 0.05;
const TICK_TIMER_FAKES = ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] as const;

function makeRows(count: number): Row[] {
  return Array.from({ length: count }, (_, i) => ({
    symbol: `SYM${String(i).padStart(4, "0")}`,
    company: `Company ${i}`,
    industry: "Industry",
    ltp: 100 + (i % 900),
    distance_pct: -(i % 40),
    ath_date: "2026-08-01",
    one_year_return_pct: (i % 50) - 25,
    order_pct_of_sales: null,
    stance: "Watch",
    bucket: "A",
    changed: false,
  }));
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

/** Seeded generator so every run picks the same rows. */
function seeded(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

type Listener = (event: { data: unknown }) => void;

/** Same fake as the live-prices tests in ScreenerTable.test.tsx. */
class FakeEventSource {
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = 0;
  onerror: (() => void) | null = null;
  readonly url: string;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(type: string, body: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(body) });
    }
  }
}

const ROWS = makeRows(ROW_COUNT);
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (url: string) =>
    url.includes("/recent-closes")
      ? jsonResponse({ closes: {} })
      : jsonResponse({ results: ROWS, total: ROWS.length, page: 1, perPage: ROWS.length }),
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);
  // jsdom has no layout. Same mocks as ScreenerTable.test.tsx so the virtualizer renders a window.
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, top: 0, left: 0, bottom: 600, right: 800, width: 800, height: 600, toJSON: () => ({}) } as DOMRect);
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 600 });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get(this: HTMLElement) { return this.tagName === "TR" ? 40 : 600; } });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 800 });
  FakeEventSource.instances = [];
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ScreenerTable performance at 5,000 rows", () => {
  it("mounts 5,000 rows and renders only a virtual window of them", async () => {
    const { container } = render(<ScreenerTable runId={RUN_ID} />);
    await screen.findByText(`Showing ${ROW_COUNT} of ${ROW_COUNT}`);

    const rendered = container.querySelectorAll("tbody tr[data-index]").length;
    console.log(`[perf] DOM rows rendered for ${ROW_COUNT} loaded: ${rendered}`);
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(100);
  });

  it("applies 60 one-second ticks to 5% of rows and records render cost", async () => {
    let commits = 0;
    const onRender: ProfilerOnRenderCallback = () => void (commits += 1);
    const { container } = render(
      <Profiler id="table" onRender={onRender}>
        <ScreenerTable runId={RUN_ID} live />
      </Profiler>,
    );
    await screen.findByText(`Showing ${ROW_COUNT} of ${ROW_COUNT}`);
    const source = FakeEventSource.instances[FakeEventSource.instances.length - 1];

    vi.useFakeTimers({ toFake: [...TICK_TIMER_FAKES] });
    const random = seeded(42);
    const picksPerTick = Math.round(ROW_COUNT * TICK_FRACTION);
    const perTick: { commits: number; ms: number }[] = [];

    for (let tick = 0; tick < TICKS; tick += 1) {
      commits = 0;
      const start = performance.now();
      act(() => {
        for (let k = 0; k < picksPerTick; k += 1) {
          const row = ROWS[Math.floor(random() * ROW_COUNT)];
          source.emit("tick", { symbol: row.symbol, ltp: 100 + random() * 900, ltt: null, cp: 100 });
        }
        vi.advanceTimersByTime(1000);
      });
      perTick.push({ commits, ms: performance.now() - start });
    }
    vi.useRealTimers();

    const avgMs = perTick.reduce((sum, t) => sum + t.ms, 0) / TICKS;
    const avgCommits = perTick.reduce((sum, t) => sum + t.commits, 0) / TICKS;
    const rowsAfter = container.querySelectorAll("tbody tr[data-index]").length;
    console.log(
      `[perf] ticks=${TICKS} picksPerTick=${picksPerTick} avgCommitsPerTick=${avgCommits.toFixed(2)} ` +
        `avgMsPerTick=${avgMs.toFixed(2)} rowsRenderedAfter=${rowsAfter}`,
    );

    expect(avgCommits).toBeGreaterThan(0);
    expect(avgMs).toBeLessThan(50);
  });
});
