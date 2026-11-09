import { useEffect, useId, useState, type FormEvent } from "react";
import { createPreset, deletePreset, listPresets, PresetsError, type Preset } from "../api/presets";
import { StateView } from "../shell/StateView";
import type { FilterState } from "./filterState";

export interface PresetsMenuProps {
  filters: FilterState;
  onApply: (filters: FilterState) => void;
}

export const PRESET_NAME_MAX = 60;

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

/** Lists, applies, saves and deletes filter presets. */
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

  return (
    <section aria-label="Filter presets" className="space-y-3 rounded-md border border-border bg-surface p-3">
      <h2 className="text-sm font-semibold text-text">Presets</h2>

      {listStatus === "loading" ? <StateView kind="loading" message="Loading presets." /> : null}
      {listStatus === "error" ? <StateView kind="error" message={`Could not load presets. ${listError ?? ""}`.trim()} /> : null}
      {listStatus === "ready" && presets.length === 0 ? (
        <StateView kind="empty" message="No saved presets." />
      ) : null}

      {listStatus === "ready" && presets.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {presets.map((preset) => (
            <li key={preset.preset_id} className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => onApply(preset.filters)}
                className="rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text"
              >
                {preset.name}
              </button>
              <button
                type="button"
                aria-label={`Delete preset ${preset.name}`}
                disabled={deletingId === preset.preset_id}
                onClick={() => onDelete(preset)}
                className="rounded-(--radius-control) px-2 py-1 text-sm text-loss disabled:opacity-60"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {deleteError ? (
        <p role="alert" className="text-sm text-loss">
          {deleteError}
        </p>
      ) : null}

      <form onSubmit={onSave} noValidate className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <label htmlFor={nameId} className="text-xs text-text-muted">
            Preset name
          </label>
          <input
            id={nameId}
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={nameError ? true : undefined}
            aria-describedby={nameError ? `${nameId}-error` : undefined}
            className="w-full min-w-0 rounded-(--radius-control) border border-border-ui bg-surface px-2 py-1 text-sm text-text"
          />
          {nameError ? (
            <span id={`${nameId}-error`} role="alert" className="text-sm text-loss">
              {nameError}
            </span>
          ) : null}
        </div>
        <button
          type="submit"
          disabled={saving}
          className="rounded-(--radius-control) border border-border-ui px-3 py-1 text-sm text-text disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save current filters"}
        </button>
      </form>
      {saveError ? (
        <p role="alert" className="text-sm text-loss">
          {saveError}
        </p>
      ) : null}
    </section>
  );
}
