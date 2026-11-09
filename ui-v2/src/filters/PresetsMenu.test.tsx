import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Preset } from "../api/presets";
import { PresetsMenu } from "./PresetsMenu";

const STORED_FILTERS = { bucket: "A", ltpMin: 100 };

const SAVED: Preset = {
  preset_id: "1",
  name: "Existing",
  filters: STORED_FILTERS,
  created_at: "2026-11-09T00:00:00Z",
  updated_at: "2026-11-09T00:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { name: string; filters: unknown };
      return jsonResponse({ ...SAVED, preset_id: "2", name: body.name, filters: body.filters }, 201);
    }
    return jsonResponse({ presets: [SAVED] });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function postCalls() {
  return fetchMock.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === "POST");
}

describe("PresetsMenu", () => {
  it("stops saving at the preset limit and sends no request", async () => {
    const six = Array.from({ length: 6 }, (_, index) => ({ ...SAVED, preset_id: `p${index}`, name: `P${index}` }));
    fetchMock.mockImplementation(async () => jsonResponse({ presets: six }));
    render(<PresetsMenu filters={{}} onApply={vi.fn()} />);
    await screen.findByRole("button", { name: "P0" });

    fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "Seventh" } });
    const save = screen.getByRole("button", { name: "Save current filters" });
    expect(save).toBeDisabled();
    fireEvent.click(save);

    expect(postCalls()).toHaveLength(0);
  });

  it("rejects an empty name without sending a request", async () => {
    render(<PresetsMenu filters={{}} onApply={vi.fn()} />);
    await screen.findByRole("button", { name: "Existing" });

    fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Save current filters" }));

    expect(await screen.findByText("Enter a name for the preset.")).toBeInTheDocument();
    expect(postCalls()).toHaveLength(0);
  });

  it("sends the trimmed name with the current filters", async () => {
    render(<PresetsMenu filters={{ bucket: "B" }} onApply={vi.fn()} />);
    await screen.findByRole("button", { name: "Existing" });

    fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "  Morning list  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save current filters" }));

    await waitFor(() => expect(postCalls()).toHaveLength(1));
    const [, init] = postCalls()[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ name: "Morning list", filters: { bucket: "B" } });
    expect(await screen.findByRole("button", { name: "Morning list" })).toBeInTheDocument();
  });

  it("apply calls onApply with the stored filters", async () => {
    const onApply = vi.fn();
    render(<PresetsMenu filters={{}} onApply={onApply} />);

    fireEvent.click(await screen.findByRole("button", { name: "Existing" }));

    expect(onApply).toHaveBeenCalledWith(STORED_FILTERS);
  });
});
