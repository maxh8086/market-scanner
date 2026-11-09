import { afterEach, describe, expect, it, vi } from "vitest";
import { createPreset, deletePreset, listPresets, PresetsError, type Preset } from "./presets";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function noContentResponse(): Response {
  return { ok: true, status: 204, json: async () => { throw new SyntaxError("no body"); } } as unknown as Response;
}

const PRESET: Preset = {
  preset_id: "7",
  name: "Watch A",
  filters: { bucket: "A", ltpMin: 100 },
  created_at: "2026-11-09T00:00:00Z",
  updated_at: "2026-11-09T00:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listPresets", () => {
  it("GETs /api/presets and returns the presets", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ presets: [PRESET] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPresets()).resolves.toEqual([PRESET]);
    expect(fetchMock).toHaveBeenCalledWith("/api/presets", {
      headers: { Accept: "application/json" },
      signal: undefined,
    });
  });

  it("passes the abort signal through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ presets: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await listPresets({ signal: controller.signal });
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ signal: controller.signal });
  });

  it("maps a server error to PresetsError with the error field as the message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: "db down" }, 500)));

    const error = await listPresets().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PresetsError);
    expect(error).toMatchObject({ message: "db down", status: 500 });
  });

  it("maps a network failure to PresetsError with a null status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await listPresets().catch((e: unknown) => e);
    expect(error).toMatchObject({ status: null, message: "Could not reach the presets service." });
  });

  it("rejects a body without a presets array", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ rows: [] })));

    await expect(listPresets()).rejects.toMatchObject({ status: 200 });
  });
});

describe("createPreset", () => {
  it("POSTs the name and filters as JSON and returns the created row", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(PRESET, 201));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createPreset("Watch A", { bucket: "A", ltpMin: 100 })).resolves.toEqual(PRESET);
    expect(fetchMock).toHaveBeenCalledWith("/api/presets", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Watch A", filters: { bucket: "A", ltpMin: 100 } }),
    });
  });

  it("maps a 400 to PresetsError carrying the server message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: "name is required" }, 400)));

    const error = await createPreset("", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PresetsError);
    expect(error).toMatchObject({ message: "name is required", status: 400 });
  });
});

describe("deletePreset", () => {
  it("DELETEs the encoded preset path and resolves on 204", async () => {
    const fetchMock = vi.fn().mockResolvedValue(noContentResponse());
    vi.stubGlobal("fetch", fetchMock);

    await expect(deletePreset("a/b")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith("/api/presets/a%2Fb", { method: "DELETE" });
  });

  it("maps a 404 to PresetsError with a generic message when the body has none", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 404)));

    const error = await deletePreset("9").catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 404, message: "Request failed with status 404." });
  });
});
