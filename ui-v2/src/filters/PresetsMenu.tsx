import { useEffect, useId, useState, type FormEvent } from "react";
import { createPreset, deletePreset, listPresets, PresetsError, type Preset } from "../api/presets";
import type { FilterState } from "./filterState";

export interface PresetsMenuProps {
  filters: FilterState;
  onApply: (filters: FilterState) => void;
}

export const PRESET_NAME_MAX = 60;
/** Most presets a user can keep. Saving stops at this count until one is deleted. */
export const PRESET_LIMIT = 6;

export type PresetNameResult = { ok: true; name: string } | { ok: false; error: string };

/** Trims a preset name and checks its length. Runs before any request is sent. */
export function checkPresetName(raw: string): PresetNameResult {
  const name = raw.trim();
  if (name.length === 0) {
    return { ok: false, error: "Enter a name for the preset." };
  }
  if (name.length > PRESET_NAME_MAX) {
    return { ok: false, error: `Preset names must be ${PRESET_NAME_MAX} characters or fewer.` };
  }
  return { ok: true, name };
}

function messageOf(error: unknown): string {
  if (error instanceof PresetsError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "Unknown error.";
}

/** Lists, applies, saves and deletes filter presets. Renders as a single row. */
export function PresetsMenu({ filters, onApply }: PresetsMenuProps) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [listStatus, setListStatus] = useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const nameId = useId();
  const atLimit = presets.length >= PRESET_LIMIT;

  useEffect(() => {
    const controller = new AbortController();
    setListStatus("loading");
    setListError(null);

    listPresets({ signal: controller.signal })
      .then((loaded) => {
        setPresets(loaded);
        setListStatus("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setListError(messageOf(error));
        setListStatus("error");
      });

    return () => controller.abort();
  }, []);

  const onSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const checked = checkPresetName(name);
    if (!checked.ok) {
      setNameError(checked.error);
      setSaveError(null);
      return;
    }
    if (atLimit) {
      setSaveError(`You can keep up to ${PRESET_LIMIT} presets. Delete one to save another.`);
      return;
    }
    setNameError(null);
    setSaveError(null);
    setSaving(true);
    try {
      const created = await createPreset(checked.name, filters);
      setPresets((current) => [created, ...current]);
      setName("");
    } catch (error: unknown) {
      setSaveError(messageOf(error));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (preset: Preset) => {
    setDeletingId(preset.preset_id);
    setDeleteError(null);
    try {
      await deletePreset(preset.preset_id);
      setPresets((current) => current.filter((item) => item.preset_id !== preset.preset_id));
    } catch (error: unknown) {
      setDeleteError(messageOf(error));
    } finally {
      setDeletingId(null);
    }
  };

  const errorText = deleteError ?? saveError ?? nameError;

  return (
    <section
      aria-label="Filter presets"
      className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-border bg-surface px-3 py-2"
    >
      <h2 className="shrink-0 text-sm font-semibold text-text">Presets</h2>

      {listStatus === "loading" ? <span className="text-sm text-text-muted">Loading presets…</span> : null}
      {listStatus === "error" ? (
        <span role="alert" className="text-sm text-loss">
          Could not load presets. {listError ?? ""}
        </span>
      ) : null}
      {listStatus === "ready" && presets.length === 0 ? (
        <span className="text-sm text-text-muted">No saved presets.</span>
      ) : null}

      {listStatus === "ready" && presets.length > 0 ? (
        <ul className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto whitespace-nowrap">
          {presets.map((preset) => (
            <li key={preset.preset_id} className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={() => onApply(preset.filters)}
                className="rounded-(--radius-control) border border-border-ui px-2 py-0.5 text-sm text-text"
              >
                {preset.name}
              </button>
              <button
                type="button"
                aria-label={`Delete preset ${preset.name}`}
                disabled={deletingId === preset.preset_id}
                onClick={() => onDelete(preset)}
                className="px-1 text-sm text-loss disabled:opacity-60"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <span className="flex-1" />
      )}

      <form onSubmit={onSave} noValidate className="flex shrink-0 items-center gap-2">
        <label htmlFor={nameId} className="sr-only">
          Preset name
        </label>
        <input
          id={nameId}
          type="text"
          value={name}
          placeholder="Preset name"
          onChange={(event) => setName(event.target.value)}
          aria-invalid={nameError ? true : undefined}
          className="w-40 min-w-0 rounded-(--radius-control) border border-border-ui bg-surface px-2 py-0.5 text-sm text-text"
        />
        <button
          type="submit"
          disabled={saving || atLimit}
          className="whitespace-nowrap rounded-(--radius-control) border border-border-ui px-2 py-0.5 text-sm text-text disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save current filters"}
        </button>
      </form>

      {errorText ? (
        <p role="alert" className="w-full text-sm text-loss">
          {errorText}
        </p>
      ) : null}
    </section>
  );
}
