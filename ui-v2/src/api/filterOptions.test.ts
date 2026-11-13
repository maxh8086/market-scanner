import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchFilterOptions, FilterOptionsError } from "./filterOptions";
import { resetCsrfTokenForTests, SESSION_URL } from "./session";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** Answers GET /api/session with a test token and every other URL with the given read. */
function withSession(read: (url: string, init?: RequestInit) => Promise<Response>) {
  return vi.fn(async (url: string, init?: RequestInit) =>
    url === SESSION_URL ? jsonResponse({ csrfToken: "test-csrf" }) : read(url, init),
  );
}

beforeEach(() => {
  resetCsrfTokenForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchFilterOptions", () => {
  it("requests the encoded run path", async () => {
    const fetchMock = withSession(async () => jsonResponse({ bucket: [], stance: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchFilterOptions("run 1/a");

    // Call 0 is the session fetch that apiGet makes first; call 1 is the filter-options read.
    expect(fetchMock.mock.calls[1][0]).toBe("/api/runs/run%201%2Fa/filter-options");
  });

  it("returns the parsed bucket and stance lists", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ bucket: ["A", "B"], stance: ["Buy"] })),
    );

    await expect(fetchFilterOptions("run-42")).resolves.toEqual({
      bucket: ["A", "B"],
      stance: ["Buy"],
    });
  });

  it("throws when a field is not an array", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ bucket: "A", stance: [] })),
    );

    const error = await fetchFilterOptions("run-42").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(FilterOptionsError);
    expect((error as FilterOptionsError).message).toBe(
      "The filter options response had an unexpected shape.",
    );
  });

  it("throws when an array holds a non-string value", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ bucket: ["A", 3], stance: [] })),
    );

    await expect(fetchFilterOptions("run-42")).rejects.toBeInstanceOf(FilterOptionsError);
  });

  it("throws with the status for a non-OK response", async () => {
    vi.stubGlobal(
      "fetch",
      withSession(async () => jsonResponse({ error: "run not found" }, 404)),
    );

    const error = await fetchFilterOptions("run-42").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(FilterOptionsError);
    expect((error as FilterOptionsError).status).toBe(404);
    expect((error as FilterOptionsError).message).toBe("run not found");
  });
});
