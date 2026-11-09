/**
 * Market session and run freshness helpers. Pure: no React, no network.
 *
 * Clock times are read in Asia/Kolkata through Intl, never by adding a fixed offset.
 *
 * Exchange holidays come from EXCHANGE_HOLIDAYS_2026 below. A holiday is a closed day, and the
 * last-close and run-age logic skip it like a weekend. The list covers 2026 only. Dates after
 * 2026-12-31 are treated as ordinary weekdays until the list is extended.
 *
 * Freshness rule: a run is expected once the session it describes has closed (15:30 IST).
 * The expected run date is the most recent weekday whose 15:30 close has passed. A run older
 * than that is stale. Its age is the number of weekdays after the run date, up to and
 * including the expected run date.
 */

export type MarketStatus = "open" | "closed" | "pre_open";

export interface MarketSession {
  status: MarketStatus;
  /** For example "Fri 13 Nov, 15:30 IST". */
  lastCloseLabel: string;
}

/**
 * NSE equity segment holidays for 2026 (weekday dates, YYYY-MM-DD).
 *
 * Source: a broker summary of the NSE holiday circulars (bajajbroking.in). Not yet checked
 * against the NSE circular itself. Verify against the circular before relying on it, and
 * update this list when the circular changes. Special sessions such as Muhurat trading are
 * not modelled.
 */
export const EXCHANGE_HOLIDAYS_2026: readonly string[] = [
  "2026-01-15", // Municipal Corporation Election, Maharashtra (unconfirmed)
  "2026-01-26", // Republic Day
  "2026-03-03", // Holi
  "2026-03-26", // Shri Ram Navami
  "2026-03-31", // Shri Mahavir Jayanti
  "2026-04-03", // Good Friday
  "2026-04-14", // Dr. Baba Saheb Ambedkar Jayanti
  "2026-05-01", // Maharashtra Day
  "2026-05-28", // Bakri Id
  "2026-06-26", // Muharram
  "2026-09-14", // Ganesh Chaturthi
  "2026-10-02", // Mahatma Gandhi Jayanti
  "2026-10-20", // Dussehra
  "2026-11-10", // Diwali Balipratipada
  "2026-11-24", // Prakash Gurpurb Sri Guru Nanak Dev
  "2026-12-25", // Christmas
];

const HOLIDAY_SET: ReadonlySet<string> = new Set(EXCHANGE_HOLIDAYS_2026);

const IST_TIME_ZONE = "Asia/Kolkata";
const PRE_OPEN_START = 9 * 60; // 09:00
const OPEN_START = 9 * 60 + 15; // 09:15
const CLOSE_TIME = 15 * 60 + 30; // 15:30
const DAY_MS = 86_400_000;
const RUN_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

const istFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: IST_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const closeLabelFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: "UTC",
  weekday: "short",
  day: "numeric",
  month: "short",
});

interface IstClock {
  /** Whole days since 1970-01-01 for the IST calendar date. */
  day: number;
  /** Minutes since IST midnight. */
  minutes: number;
}

function partOf(parts: Intl.DateTimeFormatPart[], type: string): string {
  return parts.find((part) => part.type === type)?.value ?? "";
}

function dayNumber(year: number, month: number, date: number): number {
  return Math.floor(Date.UTC(year, month - 1, date) / DAY_MS);
}

function readIstClock(now: Date): IstClock {
  const parts = istFormatter.formatToParts(now);
  const day = dayNumber(
    Number(partOf(parts, "year")),
    Number(partOf(parts, "month")),
    Number(partOf(parts, "day")),
  );
  const minutes = Number(partOf(parts, "hour")) * 60 + Number(partOf(parts, "minute"));
  return { day, minutes };
}

function isTradingDay(day: number): boolean {
  const date = new Date(day * DAY_MS);
  const weekday = date.getUTCDay();
  if (weekday === 0 || weekday === 6) {
    return false;
  }
  return !HOLIDAY_SET.has(date.toISOString().slice(0, 10));
}

/** The most recent weekday whose 15:30 IST close has passed. */
function lastCloseDay(now: Date): number {
  const clock = readIstClock(now);
  let day = clock.day;
  const todayHasClosed = clock.minutes >= CLOSE_TIME;
  if (!(todayHasClosed && isTradingDay(day))) {
    day -= 1;
  }
  while (!isTradingDay(day)) {
    day -= 1;
  }
  return day;
}

function formatCloseLabel(day: number): string {
  const parts = closeLabelFormatter.formatToParts(new Date(day * DAY_MS));
  return `${partOf(parts, "weekday")} ${partOf(parts, "day")} ${partOf(parts, "month")}, 15:30 IST`;
}

export function getMarketSession(now: Date): MarketSession {
  const clock = readIstClock(now);
  let status: MarketStatus = "closed";
  if (isTradingDay(clock.day)) {
    if (clock.minutes >= PRE_OPEN_START && clock.minutes < OPEN_START) {
      status = "pre_open";
    } else if (clock.minutes >= OPEN_START && clock.minutes < CLOSE_TIME) {
      status = "open";
    }
  }
  return { status, lastCloseLabel: formatCloseLabel(lastCloseDay(now)) };
}

/**
 * Number of weekdays after the run date, up to and including the expected run date.
 * 0 when the run is current. A malformed runDate counts as 0 (not stale), because the
 * banner must not claim an age it cannot compute.
 */
export function runAgeDays(runDate: string, now: Date): number {
  const match = RUN_DATE_PATTERN.exec(runDate);
  if (!match) {
    return 0;
  }
  const runDay = dayNumber(Number(match[1]), Number(match[2]), Number(match[3]));
  const expectedDay = lastCloseDay(now);
  let age = 0;
  for (let day = runDay + 1; day <= expectedDay; day += 1) {
    if (isTradingDay(day)) {
      age += 1;
    }
  }
  return age;
}

export function isRunStale(runDate: string, now: Date): boolean {
  return runAgeDays(runDate, now) > 0;
}
