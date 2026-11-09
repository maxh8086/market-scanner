/** Fixed size, so the column never changes width as data arrives. */
export const SPARKLINE_WIDTH = 80;
export const SPARKLINE_HEIGHT = 24;
const PADDING = 2;
const EMPTY_TEXT = "—";
const NOT_AVAILABLE = "Not available";

export type SparklineTrend = "up" | "down" | "flat";

interface SparklinePoints {
  points: string;
  trend: SparklineTrend;
}

/**
 * Plots closes (oldest first) into the SVG box. Trend compares the last close with the first one.
 * A flat series is drawn at the vertical middle.
 */
export function sparklinePoints(closes: readonly number[]): SparklinePoints {
  const first = closes[0];
  const last = closes[closes.length - 1];
  const trend: SparklineTrend = last > first ? "up" : last < first ? "down" : "flat";

  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min;
  const usableHeight = SPARKLINE_HEIGHT - PADDING * 2;
  const step = (SPARKLINE_WIDTH - PADDING * 2) / (closes.length - 1);

  const points = closes
    .map((close, index) => {
      const x = PADDING + index * step;
      const ratio = range === 0 ? 0.5 : (close - min) / range;
      const y = PADDING + (1 - ratio) * usableHeight;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return { points, trend };
}

const TREND_CLASS: Record<SparklineTrend, string> = {
  up: "text-gain",
  down: "text-loss",
  flat: "text-neutral",
};

const TREND_WORD: Record<SparklineTrend, string> = {
  up: "rising",
  down: "falling",
  flat: "flat",
};

export interface SparklineProps {
  /** Closes, oldest first. Fewer than two values draws the empty dash. */
  closes: readonly number[] | null | undefined;
}

/**
 * Inline SVG of recent closes. The line takes the gain or loss colour. The trend is also in the
 * accessible name, so colour is not the only signal. With no data it shows a dash, and the
 * tooltip and accessible name say "Not available".
 */
export function Sparkline({ closes }: SparklineProps) {
  if (!closes || closes.length < 2) {
    return (
      <span
        role="img"
        aria-label={NOT_AVAILABLE}
        title={NOT_AVAILABLE}
        data-sparkline="none"
        className="inline-block text-center align-middle text-text-muted"
        style={{ width: SPARKLINE_WIDTH }}
      >
        {EMPTY_TEXT}
      </span>
    );
  }

  const { points, trend } = sparklinePoints(closes);
  return (
    <svg
      role="img"
      aria-label={`Trend ${TREND_WORD[trend]} over the last ${closes.length} closes`}
      data-sparkline={trend}
      width={SPARKLINE_WIDTH}
      height={SPARKLINE_HEIGHT}
      viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`}
      focusable="false"
      className={`inline-block shrink-0 align-middle ${TREND_CLASS[trend]}`}
      style={{ width: SPARKLINE_WIDTH, height: SPARKLINE_HEIGHT }}
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
