import Fastify, { type FastifyInstance } from "fastify";
import {
  buildCountQuery,
  buildResultsQuery,
  buildRunLookupQuery,
  isIsoDate,
  normalizePaging,
  type ResultsParams,
} from "./results.js";

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

  return app;
}
