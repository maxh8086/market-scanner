import { useId, type ReactNode } from "react";
import type { FilterState } from "./filterState";

export interface FilterBarProps {
  value: FilterState;
  onChange: (next: FilterState) => void;
  /** Bucket values offered by the server. Only "All" is offered when none are given. */
  bucketOptions?: readonly string[];
  /** Stance values offered by the server. Only "All" is offered when none are given. */
  stanceOptions?: readonly string[];
}

const NO_OPTIONS: readonly string[] = [];

const CONTROL_CLASS =
  "w-full min-w-0 rounded-(--radius-control) border border-border-ui bg-surface px-2 py-1 text-sm text-text";

/** Sets one filter key. An empty value removes the key so it is not sent. */
function setField(value: FilterState, key: keyof FilterState, next: string | number | undefined): FilterState {
  const copy: Record<string, unknown> = { ...value };
  if (next === undefined || next === "") {
    delete copy[key];
  } else {
    copy[key] = next;
  }
  return copy as FilterState;
}

function numberOrUndefined(raw: string): number | undefined {
  if (raw.trim() === "") {
    return undefined;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

interface FieldProps {
  id: string;
  label: string;
  children: ReactNode;
}

function Field({ id, label, children }: FieldProps) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-xs text-text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

/** Controlled filter inputs for the results table. Every change reports the full next filter state. */
export function FilterBar({
  value,
  onChange,
  bucketOptions = NO_OPTIONS,
  stanceOptions = NO_OPTIONS,
}: FilterBarProps) {
  const ids = {
    bucket: useId(),
    stance: useId(),
    search: useId(),
    industry: useId(),
    ltpMin: useId(),
    ltpMax: useId(),
    distanceMin: useId(),
    distanceMax: useId(),
    athFrom: useId(),
    athTo: useId(),
  };

  return (
    <form
      aria-label="Filter results"
      className="rounded-md border border-border bg-surface p-3"
      onSubmit={(event) => event.preventDefault()}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field id={ids.bucket} label="Bucket">
          <select
            id={ids.bucket}
            className={CONTROL_CLASS}
            value={value.bucket ?? ""}
            onChange={(event) => onChange(setField(value, "bucket", event.target.value))}
          >
            <option value="">All</option>
            {bucketOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </Field>

        <Field id={ids.stance} label="Stance">
          <select
            id={ids.stance}
            className={CONTROL_CLASS}
            value={value.stance ?? ""}
            onChange={(event) => onChange(setField(value, "stance", event.target.value))}
          >
            <option value="">All</option>
            {stanceOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </Field>

        <Field id={ids.search} label="Symbol or company">
          <input
            id={ids.search}
            type="text"
            className={CONTROL_CLASS}
            value={value.search ?? ""}
            onChange={(event) => onChange(setField(value, "search", event.target.value))}
          />
        </Field>

        <Field id={ids.industry} label="Sector">
          <input
            id={ids.industry}
            type="text"
            className={CONTROL_CLASS}
            value={value.industry ?? ""}
            onChange={(event) => onChange(setField(value, "industry", event.target.value))}
          />
        </Field>

        <Field id={ids.ltpMin} label="LTP min">
          <input
            id={ids.ltpMin}
            type="number"
            inputMode="decimal"
            className={CONTROL_CLASS}
            value={value.ltpMin ?? ""}
            onChange={(event) => onChange(setField(value, "ltpMin", numberOrUndefined(event.target.value)))}
          />
        </Field>

        <Field id={ids.ltpMax} label="LTP max">
          <input
            id={ids.ltpMax}
            type="number"
            inputMode="decimal"
            className={CONTROL_CLASS}
            value={value.ltpMax ?? ""}
            onChange={(event) => onChange(setField(value, "ltpMax", numberOrUndefined(event.target.value)))}
          />
        </Field>

        <Field id={ids.distanceMin} label="From ATH min (%)">
          <input
            id={ids.distanceMin}
            type="number"
            inputMode="decimal"
            className={CONTROL_CLASS}
            value={value.distanceMin ?? ""}
            onChange={(event) =>
              onChange(setField(value, "distanceMin", numberOrUndefined(event.target.value)))
            }
          />
        </Field>

        <Field id={ids.distanceMax} label="From ATH max (%)">
          <input
            id={ids.distanceMax}
            type="number"
            inputMode="decimal"
            className={CONTROL_CLASS}
            value={value.distanceMax ?? ""}
            onChange={(event) =>
              onChange(setField(value, "distanceMax", numberOrUndefined(event.target.value)))
            }
          />
        </Field>

        <Field id={ids.athFrom} label="ATH date from">
          <input
            id={ids.athFrom}
            type="date"
            className={CONTROL_CLASS}
            value={value.athFrom ?? ""}
            onChange={(event) => onChange(setField(value, "athFrom", event.target.value))}
          />
        </Field>

        <Field id={ids.athTo} label="ATH date to">
          <input
            id={ids.athTo}
            type="date"
            className={CONTROL_CLASS}
            value={value.athTo ?? ""}
            onChange={(event) => onChange(setField(value, "athTo", event.target.value))}
          />
        </Field>
      </div>

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={() => onChange({})}
          className="rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text"
        >
          Clear filters
        </button>
      </div>
    </form>
  );
}
