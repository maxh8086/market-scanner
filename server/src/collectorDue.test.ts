import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  buildDueQueries,
  computeDue,
  isConnectionError,
  mapDueRows,
  parseServicesFile,
  toIstIso,
  type ComputeDueInput,
  type ServicesFile,
} from "./collectorDue.js";

interface Vector {
  name: string;
  engines: string[];
  mode: string;
  cron: string;
  now: string;
  last_ok: string | null;
  last_attempt: { at: string; status: string } | null;
  cooldown_until: string | null;
  open_request: boolean;
  expected_due: boolean;
  expected_reason: "slot" | "catchup" | "request" | null;
}

const vectorFile = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../tests/data/collector_due_vectors.json", import.meta.url)), "utf8"),
) as { version: number; cases: Vector[] };

const CASE_SRC = "case_src";
const HOST = "nse";
const REQUEST_ID = "00000000-0000-4000-8000-000000000001";
const MON_1900 = new Date("2026-11-16T19:00:00+05:30");

function baseInput(overrides: Partial<ComputeDueInput> = {}): ComputeDueInput {
  return {
    now: MON_1900,
    services: { sources: {} },
    settings: [],
    lastOk: new Map(),
    lastAttempt: new Map(),
    cooldowns: new Map(),
    requests: new Map(),
    ...overrides,
  };
}

function scheduled(source: string, cron: string) {
  return { source, mode: "scheduled", cron };
}

describe("collector due vectors (shared with the Python half)", () => {
  it("loads the version 1 vector file with cases", () => {
    expect(vectorFile.version).toBe(1);
    expect(vectorFile.cases.length).toBeGreaterThanOrEqual(21);
  });

  for (const c of vectorFile.cases) {
    it(`${c.name} (${c.engines.join("+")})`, () => {
      const services: ServicesFile = { sources: { [CASE_SRC]: { service: CASE_SRC, host: HOST } } };
      const result = computeDue(
        baseInput({
          now: new Date(c.now),
          services,
          settings: [{ source: CASE_SRC, mode: c.mode, cron: c.cron }],
          lastOk: c.last_ok ? new Map([[CASE_SRC, new Date(c.last_ok)]]) : new Map(),
          lastAttempt: c.last_attempt
            ? new Map([[CASE_SRC, { startedAt: new Date(c.last_attempt.at), status: c.last_attempt.status }]])
            : new Map(),
          cooldowns: c.cooldown_until ? new Map([[HOST, new Date(c.cooldown_until)]]) : new Map(),
          requests: c.open_request ? new Map([[CASE_SRC, REQUEST_ID]]) : new Map(),
        }),
      );

      expect(result.skipped).toEqual([]);
      expect(result.sources.length > 0).toBe(c.expected_due);
      if (c.expected_due) {
        expect(result.sources[0].reason).toBe(c.expected_reason);
        expect(result.sources[0].request_id).toBe(c.expected_reason === "request" ? REQUEST_ID : null);
      }
    });
  }
});

describe("computeDue rules beyond the vectors", () => {
  it("a slot exactly at now is the latest slot (reason slot, age 0)", () => {
    const result = computeDue(
      baseInput({
        now: new Date("2026-11-16T18:35:00+05:30"),
        services: { sources: { [CASE_SRC]: { service: CASE_SRC } } },
        settings: [scheduled(CASE_SRC, "35 18 * * 1-5")],
      }),
    );
    expect(result.sources).toEqual([
      { name: CASE_SRC, service: CASE_SRC, reason: "slot", request_id: null, order: 1 },
    ]);
  });

  it("an ok run exactly at the latest slot is not due again", () => {
    const result = computeDue(
      baseInput({
        now: new Date("2026-11-16T18:35:00+05:30"),
        services: { sources: { [CASE_SRC]: { service: CASE_SRC } } },
        settings: [scheduled(CASE_SRC, "35 18 * * 1-5")],
        lastOk: new Map([[CASE_SRC, new Date("2026-11-16T18:35:00+05:30")]]),
      }),
    );
    expect(result.sources).toEqual([]);
  });

  it("sources not in the services file are never returned", () => {
    const result = computeDue(
      baseInput({
        services: { sources: { [CASE_SRC]: { service: CASE_SRC } } },
        settings: [scheduled("ghost", "35 18 * * 1-5"), scheduled(CASE_SRC, "35 18 * * 1-5")],
        requests: new Map([["ghost", REQUEST_ID]]),
      }),
    );
    expect(result.sources.map((s) => s.name)).toEqual([CASE_SRC]);
  });

  it("orders index_eod, candles_eod, then the rest by name, with order 1..n", () => {
    const names = ["zeta", "candles_eod", "index_eod", "alpha", "fundamentals"];
    const sources: ServicesFile["sources"] = {};
    for (const name of names) sources[name] = { service: name };
    const result = computeDue(
      baseInput({
        services: { sources },
        settings: names.map((name) => scheduled(name, "35 18 * * 1-5")),
      }),
    );
    expect(result.sources.map((s) => s.name)).toEqual(["index_eod", "candles_eod", "alpha", "fundamentals", "zeta"]);
    expect(result.sources.map((s) => s.order)).toEqual([1, 2, 3, 4, 5]);
  });

  it("fundamentals returns nothing on the manual or ok-run path, and never queue or stale", () => {
    const services: ServicesFile = { sources: { fundamentals: { service: "fundamentals" } } };
    const manual = computeDue(
      baseInput({ services, settings: [{ source: "fundamentals", mode: "manual", cron: "" }] }),
    );
    expect(manual.sources).toEqual([]);

    const okAfterSlot = computeDue(
      baseInput({
        services,
        settings: [scheduled("fundamentals", "35 18 * * 1-5")],
        lastOk: new Map([["fundamentals", new Date("2026-11-16T18:40:00+05:30")]]),
      }),
    );
    expect(okAfterSlot.sources).toEqual([]);

    const reasons = [...manual.sources, ...okAfterSlot.sources].map((s) => s.reason as string);
    expect(reasons).not.toContain("queue");
    expect(reasons).not.toContain("stale");
  });

  it("a host with no cooldown row is not omitted", () => {
    const result = computeDue(
      baseInput({
        services: { sources: { [CASE_SRC]: { service: CASE_SRC, host: HOST } } },
        settings: [scheduled(CASE_SRC, "35 18 * * 1-5")],
        cooldowns: new Map([["other_host", new Date("2026-11-16T23:00:00+05:30")]]),
      }),
    );
    expect(result.sources.map((s) => s.name)).toEqual([CASE_SRC]);
  });

  it("an invalid cron skips that source into skipped and never throws", () => {
    const result = computeDue(
      baseInput({
        services: { sources: { bad: { service: "bad" }, good: { service: "good" } } },
        settings: [scheduled("bad", "not a cron"), scheduled("good", "35 18 * * 1-5")],
      }),
    );
    expect(result.skipped).toEqual(["bad"]);
    expect(result.sources.map((s) => s.name)).toEqual(["good"]);
  });
});

describe("row mapping and services parsing", () => {
  it("maps the five query row shapes onto the inputs", () => {
    const inputs = mapDueRows({
      settings: [{ source: "a", mode: "scheduled", cron: "35 18 * * 1-5" }],
      lastOk: [{ source: "a", started_at: new Date("2026-11-13T18:40:00+05:30") }],
      lastAttempt: [{ source: "a", started_at: "2026-11-16T18:40:00+05:30", status: "failed" }],
      requests: [{ id: REQUEST_ID, source: "a" }],
      cooldowns: [{ host: "nse", cooldown_until: "2026-11-16T19:30:00+05:30" }],
    });
    expect(inputs.settings).toEqual([{ source: "a", mode: "scheduled", cron: "35 18 * * 1-5" }]);
    expect(inputs.lastOk.get("a")?.toISOString()).toBe("2026-11-13T13:10:00.000Z");
    expect(inputs.lastAttempt.get("a")?.status).toBe("failed");
    expect(inputs.requests.get("a")).toBe(REQUEST_ID);
    expect(inputs.cooldowns.get("nse")?.toISOString()).toBe("2026-11-16T14:00:00.000Z");
  });

  it("builds the five parameter-free statements from the contract", () => {
    const q = buildDueQueries();
    expect(q.settings).toBe("SELECT source, mode, cron FROM collector_settings");
    expect(q.requests).toBe("SELECT id, source FROM collector_requests WHERE claimed_at IS NULL");
    expect(q.cooldowns).toBe("SELECT host, cooldown_until FROM source_cooldown");
    expect(q.lastOk).toContain("WHERE status = 'ok' ORDER BY source, started_at DESC");
    expect(q.lastAttempt).toContain("ORDER BY source, started_at DESC");
  });

  it("formats generated_at as an ISO instant with +05:30", () => {
    expect(toIstIso(new Date("2026-11-16T13:30:00.000Z"))).toBe("2026-11-16T19:00:00.000+05:30");
  });

  it("parses a valid services file and rejects a bad shape", () => {
    expect(parseServicesFile('{"sources": {"a": {"service": "svc", "host": "nse"}, "b": {"service": "x"}}}')).toEqual({
      sources: { a: { service: "svc", host: "nse" }, b: { service: "x" } },
    });
    expect(() => parseServicesFile('{"sources": []}')).toThrow();
    expect(() => parseServicesFile('{"sources": {"a": {"host": "nse"}}}')).toThrow();
    expect(() => parseServicesFile("not json")).toThrow();
  });

  it("parses the real config/collector_services.json and maps home_filings", () => {
    const text = readFileSync(fileURLToPath(new URL("../../config/collector_services.json", import.meta.url)), "utf8");
    const services = parseServicesFile(text);
    expect(services.sources.home_filings).toEqual({ service: "collector-home-filings", host: "nse" });
  });

  it("recognises connection-class errors only", () => {
    expect(isConnectionError(Object.assign(new Error("x"), { code: "08006" }))).toBe(true);
    expect(isConnectionError(Object.assign(new Error("x"), { code: "ETIMEDOUT" }))).toBe(true);
    expect(isConnectionError(new Error("Connection terminated unexpectedly"))).toBe(true);
    expect(isConnectionError(Object.assign(new Error("x"), { code: "42P01" }))).toBe(false);
    expect(isConnectionError(new Error("relation missing"))).toBe(false);
  });
});
