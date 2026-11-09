import Fastify, { type FastifyInstance } from "fastify";
import {
  buildCountQuery,
  buildLatestRunQuery,
  buildResultsQuery,
  buildRunLookupQuery,
  formatRunDate,
  isIsoDate,
  normalizePaging,
  type ResultsParams,
} from "./results.js";
import {
  buildFilterOptionsQuery,
  shapeFilterOptions,
} from "./filterOptions.js";
import {
  buildDeletePresetQuery,
  buildInsertPresetQuery,
  buildListPresetsQuery,
  validatePresetInput,
} from "./presets.js";

export interface QueryResult {
  rows: Array<Record<string, unknown>>;
}

export type QueryFn = (sql: string, values: unknown[]) => Promise<QueryResult>;

export interface AppDeps {
  query: QueryFn;
  logger?: boolean;
}

type ResultsQueryString = Omit<ResultsParams, "runId">;

const resultsQuerySchema = {
  type: "object",
  properties: {
    page: { type: "integer", minimum: 1 },
    perPage: { type: "integer", minimum: 1, maximum: 100 },
    sort: { type: "string", maxLength: 64 },
    order: { type: "string", enum: ["asc", "desc"] },
    bucket: { type: "string", maxLength: 64 },
    stance: { type: "string", maxLength: 64 },
    search: { type: "string", maxLength: 128 },
    industry: { type: "string", maxLength: 128 },
    ltpMin: { type: "number" },
    ltpMax: { type: "number" },
    distanceMin: { type: "number" },
    distanceMax: { type: "number" },
    athFrom: { type: "string", maxLength: 10 },
    athTo: { type: "string", maxLength: 10 },
  },
} as const;

export function buildApp(deps: AppDeps): FastifyInstance {
  const app = Fastify({ logger: deps.logger ?? false });

  app.get("/api/health", async () => ({ ok: true }));

  // Registered before any /api/runs/:runId route so "latest" is not read as an id.
  app.get("/api/runs/latest", async (_request, reply) => {
    const latest = buildLatestRunQuery();
    const found = await deps.query(latest.sql, latest.values);
    const row = found.rows[0];
    if (!row) {
      return reply.code(404).send({ error: "No current run" });
    }
    const runDate = formatRunDate(row.run_date);
    return { runId: String(row.run_id), runDate };
  });

  app.get<{ Params: { runId: string }; Querystring: ResultsQueryString }>(
    "/api/runs/:runId/results",
    { schema: { querystring: resultsQuerySchema } },
    async (request, reply) => {
      const lookup = buildRunLookupQuery(request.params.runId);
      if (!lookup) {
        return reply.code(404).send({ error: "Run not found" });
      }

      for (const field of ["athFrom", "athTo"] as const) {
        const value = request.query[field];
        if (value && !isIsoDate(value)) {
          return reply.code(400).send({ error: `Invalid ${field}` });
        }
      }

      const found = await deps.query(lookup.sql, lookup.values);
      const resolvedRunId = found.rows[0]?.run_id;
      if (resolvedRunId === undefined || resolvedRunId === null) {
        return reply.code(404).send({ error: "Run not found" });
      }

      const params: ResultsParams = { ...request.query, runId: String(resolvedRunId) };
      const { page, perPage } = normalizePaging(request.query.page, request.query.perPage);
      const rowsQuery = buildResultsQuery(params);
      const countQuery = buildCountQuery(params);

      const [rowsResult, countResult] = await Promise.all([
        deps.query(rowsQuery.sql, rowsQuery.values),
        deps.query(countQuery.sql, countQuery.values),
      ]);

      return {
        results: rowsResult.rows,
        total: Number(countResult.rows[0]?.total ?? 0),
        page,
        perPage,
      };
    },
  );

  // Distinct bucket and stance values for a run. An unknown or malformed run id
  // returns empty lists (no 404), so the UI can show empty dropdowns.
  app.get<{ Params: { runId: string } }>(
    "/api/runs/:runId/filter-options",
    async (request) => {
      const empty = { bucket: [], stance: [] };
      const lookup = buildRunLookupQuery(request.params.runId);
      if (!lookup) return empty;

      const found = await deps.query(lookup.sql, lookup.values);
      const resolvedRunId = found.rows[0]?.run_id;
      if (resolvedRunId === undefined || resolvedRunId === null) return empty;

      const options = buildFilterOptionsQuery(String(resolvedRunId));
      const result = await deps.query(options.sql, options.values);
      return shapeFilterOptions(result.rows);
    },
  );

  // Saved scan presets. The write path validates every field before any SQL runs.
  app.get("/api/presets", async () => {
    const listing = buildListPresetsQuery();
    const found = await deps.query(listing.sql, listing.values);
    return { presets: found.rows };
  });

  app.post<{ Body: unknown }>("/api/presets", async (request, reply) => {
    const checked = validatePresetInput(request.body);
    if (!checked.ok) {
      return reply.code(400).send({ error: checked.error });
    }
    const insert = buildInsertPresetQuery(checked.value);
    const created = await deps.query(insert.sql, insert.values);
    return reply.code(201).send(created.rows[0]);
  });

  app.delete<{ Params: { presetId: string } }>(
    "/api/presets/:presetId",
    async (request, reply) => {
      const checked = buildDeletePresetQuery(request.params.presetId);
      if (!checked.ok) {
        return reply.code(400).send({ error: checked.error });
      }
      const removed = await deps.query(checked.value.sql, checked.value.values);
      if (removed.rows.length === 0) {
        return reply.code(404).send({ error: "Preset not found" });
      }
      return reply.code(204).send();
    },
  );

  return app;
}
