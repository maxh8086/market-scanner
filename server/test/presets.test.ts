import { describe, expect, it } from "vitest";
import { buildApp, type QueryFn } from "../src/app.js";
import {
  buildDeletePresetQuery,
  buildInsertPresetQuery,
  buildListPresetsQuery,
  validatePresetInput,
} from "../src/presets.js";

const PRESET_ID = "9b2e4c1a-3f5d-4e6a-8b7c-0d1e2f3a4b5c";

function fakeQuery(rows: Array<Record<string, unknown>>): {
  query: QueryFn;
  calls: Array<{ sql: string; values: unknown[] }>;
} {
  const calls: Array<{ sql: string; values: unknown[] }> = [];
  const query: QueryFn = async (sql, values) => {
    calls.push({ sql, values });
    return { rows };
  };
  return { query, calls };
}

describe("validatePresetInput", () => {
  it("accepts a good body and trims the name", () => {
    const res = validatePresetInput({
      name: "  Breakouts  ",
      filters: { bucket: "A", ltpMin: 10, athFrom: "2026-01-02", search: "tata" },
    });
    expect(res).toEqual({
      ok: true,
      value: {
        name: "Breakouts",
        filters: { bucket: "A", ltpMin: 10, athFrom: "2026-01-02", search: "tata" },
      },
    });
  });

  it("rejects an empty name", () => {
    expect(validatePresetInput({ name: "   ", filters: {} })).toEqual({
      ok: false,
      error: "name is required",
    });
  });

  it("rejects a name over 60 characters", () => {
    const res = validatePresetInput({ name: "x".repeat(61), filters: {} });
    expect(res.ok).toBe(false);
  });

  it("accepts a name of exactly 60 characters", () => {
    expect(validatePresetInput({ name: "x".repeat(60), filters: {} }).ok).toBe(true);
  });

  it("rejects an unknown filter key", () => {
    const res = validatePresetInput({ name: "a", filters: { sort: "symbol" } });
    expect(res).toEqual({ ok: false, error: "Unknown filter key: sort" });
  });

  it("rejects a bad date", () => {
    expect(validatePresetInput({ name: "a", filters: { athFrom: "2026-02-30" } }).ok).toBe(false);
    expect(validatePresetInput({ name: "a", filters: { athTo: "02/01/2026" } }).ok).toBe(false);
  });

  it("rejects more than 20 filter keys", () => {
    const filters: Record<string, number> = {};
    for (let i = 0; i < 21; i++) filters[`k${i}`] = i;
    const res = validatePresetInput({ name: "a", filters });
    expect(res.ok).toBe(false);
  });

  it("rejects a non-object filters value", () => {
    for (const filters of [[], "bucket=A", null, 5]) {
      expect(validatePresetInput({ name: "a", filters }).ok).toBe(false);
    }
  });

  it("rejects a non-object body", () => {
    expect(validatePresetInput(undefined).ok).toBe(false);
    expect(validatePresetInput([]).ok).toBe(false);
  });

  it("rejects non-finite numbers and over-long strings", () => {
    expect(validatePresetInput({ name: "a", filters: { ltpMax: Infinity } }).ok).toBe(false);
    expect(validatePresetInput({ name: "a", filters: { stance: "s".repeat(201) } }).ok).toBe(false);
  });
});

describe("preset SQL builders", () => {
  it("builds a parameterised list query ordered by name", () => {
    const { sql, values } = buildListPresetsQuery();
    expect(sql).toContain("FROM scan_presets");
    expect(sql).toContain("ORDER BY name");
    expect(values).toEqual([]);
  });

  it("builds an insert with placeholders and RETURNING", () => {
    const { sql, values } = buildInsertPresetQuery({ name: "A", filters: { bucket: "B" } });
    expect(sql).toContain("INSERT INTO scan_presets");
    expect(sql).toContain("VALUES ($1, $2::jsonb)");
    expect(sql).toContain("RETURNING preset_id, name, filters, created_at, updated_at");
    expect(values).toEqual(["A", JSON.stringify({ bucket: "B" })]);
  });

  it("builds a delete with one placeholder for a valid UUID", () => {
    const res = buildDeletePresetQuery(PRESET_ID);
    expect(res).toEqual({
      ok: true,
      value: {
        sql: "DELETE FROM scan_presets WHERE preset_id = $1 RETURNING preset_id",
        values: [PRESET_ID],
      },
    });
  });

  it("returns a validation error and no query for a bad id", () => {
    expect(buildDeletePresetQuery("not-a-uuid")).toEqual({ ok: false, error: "Invalid presetId" });
  });
});

describe("/api/presets routes", () => {
  it("GET returns presets in a presets array", async () => {
    const row = {
      preset_id: PRESET_ID,
      name: "A",
      filters: { bucket: "B" },
      created_at: "2026-01-02T00:00:00.000Z",
      updated_at: "2026-01-02T00:00:00.000Z",
    };
    const { query, calls } = fakeQuery([row]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "GET", url: "/api/presets" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ presets: [row] });
    expect(calls[0].sql).toContain("FROM scan_presets");
  });

  it("POST returns 201 with the created row", async () => {
    const created = { preset_id: PRESET_ID, name: "A", filters: { bucket: "B" } };
    const { query, calls } = fakeQuery([created]);
    const app = buildApp({ query });
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      payload: { name: " A ", filters: { bucket: "B" } },
    });
    expect(res.statusCode).toBe(201);
    expect(res.json()).toEqual(created);
    expect(calls[0].values).toEqual(["A", JSON.stringify({ bucket: "B" })]);
  });

  it("POST returns 400 with an error on validation failure and runs no query", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({
      method: "POST",
      url: "/api/presets",
      payload: { name: "", filters: {} },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "name is required" });
    expect(calls).toHaveLength(0);
  });

  it("POST returns 400 when the body is missing", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "POST", url: "/api/presets" });
    expect(res.statusCode).toBe(400);
    expect(calls).toHaveLength(0);
  });

  it("DELETE returns 204 when a row was removed", async () => {
    const { query, calls } = fakeQuery([{ preset_id: PRESET_ID }]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "DELETE", url: `/api/presets/${PRESET_ID}` });
    expect(res.statusCode).toBe(204);
    expect(calls[0].values).toEqual([PRESET_ID]);
  });

  it("DELETE returns 404 when no row matched", async () => {
    const { query } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "DELETE", url: `/api/presets/${PRESET_ID}` });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toEqual({ error: "Preset not found" });
  });

  it("DELETE returns 400 for a bad id and runs no query", async () => {
    const { query, calls } = fakeQuery([]);
    const app = buildApp({ query });
    const res = await app.inject({ method: "DELETE", url: "/api/presets/nope" });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: "Invalid presetId" });
    expect(calls).toHaveLength(0);
  });
});
