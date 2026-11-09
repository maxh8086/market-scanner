import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, type CandlestickData, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { CandlesError, fetchCandles, type Candle } from "../api/candles";
import { formatInr, formatPercentWithArrow } from "../lib/format";
import { StateView } from "../shell/StateView";

export interface StockPageProps {
  symbol: string;
  company: string | null;
}

const CANDLE_LIMIT = 500;
const CHART_HEIGHT = 360;

/** Sections the API does not serve yet. They show a placeholder rather than invented data. */
const PLACEHOLDER_SECTIONS = ["Announcements", "Fundamentals", "Concall summaries", "Order book", "Guidelines"];

type CandlesState =
  | { status: "loading" }
  | { status: "ready"; candles: Candle[] }
  | { status: "empty" }
  | { status: "error"; message: string };

const EMPTY_TEXT = "—";

function messageOf(error: unknown): string {
  if (error instanceof CandlesError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "Could not load candles.";
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

/** Only candles with a full OHLC set can be drawn. */
function drawableCandles(candles: Candle[]): CandlestickData<Time>[] {
  const data: CandlestickData<Time>[] = [];
  for (const candle of candles) {
    if (candle.open === null || candle.high === null || candle.low === null || candle.close === null) {
      continue;
    }
    data.push({ time: candle.date as Time, open: candle.open, high: candle.high, low: candle.low, close: candle.close });
  }
  return data;
}

/** Latest close and the previous close, both from candles that have a close. */
function closesOf(candles: Candle[]): { latest: number; previous: number | null } | null {
  const closes = candles.map((candle) => candle.close).filter((close): close is number => close !== null);
  if (closes.length === 0) {
    return null;
  }
  return { latest: closes[closes.length - 1], previous: closes.length > 1 ? closes[closes.length - 2] : null };
}

function trendClass(value: number | null): string {
  if (value === null || Math.round(value * 100) === 0) {
    return "text-neutral";
  }
  return value > 0 ? "text-gain" : "text-loss";
}

/** Reads the chart colours from the design tokens so light and dark themes both apply. */
function readChartColors() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string) => styles.getPropertyValue(name).trim();
  return {
    surface: token("--surface"),
    text: token("--text-muted"),
    grid: token("--border"),
    gain: token("--gain"),
    loss: token("--loss"),
  };
}

interface ChartHandle {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
}

export function StockPage({ symbol, company }: StockPageProps) {
  const [state, setState] = useState<CandlesState>({ status: "loading" });
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ChartHandle | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });

    fetchCandles(symbol, { limit: CANDLE_LIMIT, signal: controller.signal })
      .then((body) => {
        const usable = body.candles.some((candle) => candle.close !== null);
        setState(usable ? { status: "ready", candles: body.candles } : { status: "empty" });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) {
          return;
        }
        setState({ status: "error", message: messageOf(error) });
      });

    return () => controller.abort();
  }, [symbol]);

  // Chart lifecycle: created once per mounted page, removed on unmount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const colors = readChartColors();
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: CHART_HEIGHT,
      layout: {
        background: { type: ColorType.Solid, color: colors.surface },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      kineticScroll: { mouse: !reduceMotion, touch: !reduceMotion },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: colors.gain,
      downColor: colors.loss,
      wickUpColor: colors.gain,
      wickDownColor: colors.loss,
      borderVisible: false,
    });
    chartRef.current = { chart, series };

    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver((entries) => {
        const width = entries[0]?.contentRect.width;
        if (width) {
          chart.applyOptions({ width: Math.floor(width) });
        }
      });
      observer.observe(container);
    }

    return () => {
      observer?.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Feed candles into the chart whenever they change.
  useEffect(() => {
    const handle = chartRef.current;
    if (!handle || state.status !== "ready") {
      return;
    }
    handle.series.setData(drawableCandles(state.candles));
    handle.chart.timeScale().fitContent();
  }, [state]);

  const closes = state.status === "ready" ? closesOf(state.candles) : null;
  const changePct =
    closes && closes.previous !== null && closes.previous !== 0
      ? ((closes.latest - closes.previous) / closes.previous) * 100
      : null;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="font-mono text-xl font-semibold text-text">{symbol}</h2>
        <p className="text-sm text-text-muted">{company ?? EMPTY_TEXT}</p>
        {closes ? (
          <p className="flex flex-wrap items-baseline gap-x-3 text-sm">
            <span className="tabular-nums text-lg font-semibold text-text">{formatInr(closes.latest)}</span>
            <span className={`tabular-nums ${trendClass(changePct)}`}>{formatPercentWithArrow(changePct)}</span>
          </p>
        ) : null}
      </header>

      <section aria-label="Price chart" className="space-y-2">
        {state.status !== "ready" ? (
          <StateView
            kind={state.status === "error" ? "error" : state.status === "empty" ? "empty" : "loading"}
            message={
              state.status === "error"
                ? state.message
                : state.status === "empty"
                  ? "No daily candles for this stock."
                  : "Loading daily candles."
            }
          />
        ) : null}
        <div
          ref={containerRef}
          hidden={state.status !== "ready"}
          style={{ height: CHART_HEIGHT }}
          className="w-full min-w-0"
        />
      </section>

      <div className="grid gap-3 md:grid-cols-2">
        {PLACEHOLDER_SECTIONS.map((title) => (
          <section key={title} aria-label={title} className="space-y-2">
            <h3 className="text-sm font-semibold text-text">{title}</h3>
            <StateView kind="empty" message="Not available yet" />
          </section>
        ))}
      </div>
    </div>
  );
}
