export interface DataAgeStampProps {
  runDate?: string | null;
  runTimestamp?: string | null;
}

export function DataAgeStamp({ runDate, runTimestamp }: DataAgeStampProps) {
  const dateLabel = runDate || runTimestamp;

  if (!dateLabel) {
    return (
      <span
        title="Not available"
        className="inline-flex items-center gap-2 text-sm text-text-muted"
      >
        <span aria-hidden="true" className="size-2 rounded-full bg-caution" />
        Data as of {"—"}
      </span>
    );
  }

  return (
    <span
      title={runTimestamp ?? undefined}
      className="inline-flex items-center gap-2 text-sm text-text-muted"
    >
      Data as of {dateLabel}
    </span>
  );
}
