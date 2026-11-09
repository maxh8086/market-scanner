export type StateKind =
  | "idle"
  | "loading"
  | "empty"
  | "error"
  | "market_closed"
  | "pre_open"
  | "stale"
  | "reconnecting";

export interface StateViewAction {
  label: string;
  onClick: () => void;
}

export interface StateViewProps {
  kind: StateKind;
  message: string;
  /** Optional button shown under the message, for example Retry or Clear filters. */
  action?: StateViewAction;
}

const CAUTION_KINDS: ReadonlySet<StateKind> = new Set<StateKind>([
  "market_closed",
  "pre_open",
  "stale",
  "reconnecting",
]);
const SKELETON_ROWS = 3;

/** Placeholder panel for loading, empty, error, no-selection and market-session states. */
export function StateView({ kind, message, action }: StateViewProps) {
  const isError = kind === "error";
  const isCaution = CAUTION_KINDS.has(kind);
  const messageClass = isError ? "text-loss" : isCaution ? "text-caution" : "text-text-muted";

  return (
    <div
      role={isError ? "alert" : "status"}
      data-state={kind}
      aria-busy={kind === "loading" ? "true" : undefined}
      className="rounded-md border border-border bg-surface p-6 text-center text-sm"
    >
      <p className={messageClass}>{message}</p>
      {kind === "loading" ? (
        <div aria-hidden="true" className="mx-auto mt-4 flex max-w-sm flex-col gap-3">
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
            <div
              key={index}
              data-skeleton-row=""
              className="h-4 rounded bg-surface-2 motion-safe:animate-pulse"
            />
          ))}
        </div>
      ) : null}
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-4 rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text"
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
