export type StateKind = "idle" | "loading" | "empty" | "error";

export interface StateViewProps {
  kind: StateKind;
  message: string;
}

/** Placeholder panel for loading, empty, error and no-selection states. */
export function StateView({ kind, message }: StateViewProps) {
  const isError = kind === "error";

  return (
    <div
      role={isError ? "alert" : "status"}
      data-state={kind}
      className="rounded-md border border-border bg-surface p-6 text-center text-sm"
    >
      <p className={isError ? "text-loss" : "text-text-muted"}>{message}</p>
    </div>
  );
}
