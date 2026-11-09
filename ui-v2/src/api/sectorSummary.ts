/** Client for GET /api/runs/:runId/sector-summary. Shape mirrors the server sector summary endpoint. */

export const SECTOR_PERIODS = ["1d", "1w", "1m", "3m", "6m", "12m"] as const;

export type SectorPeriod = (typeof SECTOR_PERIODS)[number];

export interface SectorSummaryRow {
  sector: string;
  count: number;
  avgChangePct: number;
  advancers: number;
  decliners: number;
}

export interface SectorSummaryResponse {
  period: SectorPeriod;
  sectors: SectorSummaryRow[];
}

export interface FetchSectorSummaryOptions {
  signal?: AbortSignal;
}

/** Failure from the sector summary API: a non-OK status, a network error or a bad body. */
export class SectorSummaryError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "SectorSummaryError";
    this.status = status;
  }
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error.length > 0) {
      return body.error;
    }
  } catch {
    // Body is not JSON; fall through to the generic message.
  }
  return `Request failed with status ${response.status}.`;
}

const isFiniteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function isSectorRow(value: unknown): value is SectorSummaryRow {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    typeof row.sector === "string" &&
    isFiniteNumber(row.count) &&
    isFiniteNumber(row.avgChangePct) &&
    isFiniteNumber(row.advancers) &&
    isFiniteNumber(row.decliners)
  );
}

function isSectorSummaryBody(body: unknown): body is { period: string; sectors: SectorSummaryRow[] } {
  if (typeof body !== "object" || body === null) {
    return false;
  }
  const response = body as { period?: unknown; sectors?: unknown };
  return typeof response.period === "string" && Array.isArray(response.sectors) && response.sectors.every(isSectorRow);
}

export async function fetchSectorSummary(
  runId: string,
  period: SectorPeriod,
  options: FetchSectorSummaryOptions = {},
): Promise<SectorSummaryResponse> {
  const url = `/api/runs/${encodeURIComponent(runId)}/sector-summary?period=${encodeURIComponent(period)}`;

  let response: Response;
  try {
    response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new SectorSummaryError("Could not reach the sector service.", null);
  }

  if (!response.ok) {
    throw new SectorSummaryError(await readErrorMessage(response), response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new SectorSummaryError("The sector summary response was not valid JSON.", response.status);
  }

  if (!isSectorSummaryBody(body)) {
    throw new SectorSummaryError("The sector summary response had an unexpected shape.", response.status);
  }
  return { period: body.period as SectorPeriod, sectors: body.sectors };
}
