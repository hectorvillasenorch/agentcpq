/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { saveActionTrigger, type ActionTriggerDetail } from "../../lib/api";

/** Pretty-printed JSON block (indented, monospace, horizontally scrollable). */
function JsonBlock({ value }: { value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  return (
    <pre className="m-0 overflow-auto rounded-md border border-[#EDEEF1] bg-[#F7F8FA] p-2.5 text-[12px] leading-relaxed text-foreground">
      {text}
    </pre>
  );
}

function FieldBlock({ label, value, editing, draft, onChange }: {
  label: string;
  value: unknown;
  editing: boolean;
  draft: string;
  onChange: (v: string) => void;
}) {
  if (editing) {
    return (
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
        <textarea
          className="w-full resize-y rounded-md border border-[#E2E8F0] bg-white p-2.5 font-mono text-[12px] leading-relaxed text-foreground outline-none focus:border-[#3B62D9]"
          rows={Math.min(12, Math.max(4, draft.split("\n").length + 1))}
          value={draft}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
        />
      </div>
    );
  }
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <JsonBlock value={value} />
    </div>
  );
}

export default function ActionTriggersCard({ payload }: { payload: unknown }) {
  const initial = Array.isArray(payload) ? (payload as ActionTriggerDetail[]) : [];
  const [items, setItems] = useState<ActionTriggerDetail[]>(initial);

  const [editingId, setEditingId] = useState<string | number | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!items.length) {
    return <div className="text-[13px] text-muted-foreground">No action triggers found.</div>;
  }

  const pretty = (v: unknown) => JSON.stringify(v ?? {}, null, 2);

  const startEdit = (t: ActionTriggerDetail) => {
    setEditingId(t.id ?? t.name);
    setDraft({
      name: t.name ?? "",
      description: t.description ?? "",
      event_type: pretty(t.event_type),
      conditions: pretty(t.conditions),
      actions: pretty(t.actions),
      active: String(t.active ?? true),
    });
    setError(null);
  };

  const cancel = () => {
    setEditingId(null);
    setDraft({});
    setError(null);
  };

  const save = async (t: ActionTriggerDetail) => {
    setSaving(true);
    setError(null);
    try {
      const jsonFields: Array<[string, string]> = [
        ["event_type", draft.event_type],
        ["conditions", draft.conditions],
        ["actions", draft.actions],
      ];
      const parsed: Record<string, unknown> = {};
      for (const [key, raw] of jsonFields) {
        try {
          parsed[key] = JSON.parse(raw.trim() || "null");
        } catch {
          setError(`${key.replace("_", " ")} is not valid JSON.`);
          setSaving(false);
          return;
        }
      }
      const saved = await saveActionTrigger(t.id ?? t.name, {
        name: draft.name,
        description: draft.description,
        event_type: parsed.event_type,
        conditions: parsed.conditions,
        actions: parsed.actions,
        active: draft.active === "true",
      });
      if (saved) {
        setItems((prev) => prev.map((x) => (x.id === t.id || x.name === t.name ? { ...x, ...saved } : x)));
      }
      setEditingId(null);
      setDraft({});
      setSaving(false);
    } catch {
      setError("Could not save the trigger.");
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      {items.map((t, idx) => {
        const editing = editingId === (t.id ?? t.name);
        const key = t.id ?? t.name ?? idx;
        return (
          <div key={key} className="overflow-hidden rounded-xl border border-[#EDEEF1] bg-white">
            <div className="flex items-center justify-between gap-2 border-b border-[#EDEEF1] bg-[#F7F8FA] px-4 py-2.5">
              <div className="flex items-center gap-2.5">
                <span className="text-[13px] font-semibold text-foreground">{editing ? "Edit trigger" : t.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                    t.active ? "bg-green-100 text-green-700" : "bg-muted text-muted-foreground"
                  }`}
                >
                  {t.active ? "Active" : "Inactive"}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                {!editing && (
                  <button
                    type="button"
                    onClick={() => startEdit(t)}
                    className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-foreground hover:bg-muted"
                  >
                    <Pencil size={12} /> Edit
                  </button>
                )}
                {editing && (
                  <>
                    <button
                      type="button"
                      onClick={cancel}
                      className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-foreground hover:bg-muted"
                    >
                      <X size={12} /> Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => save(t)}
                      disabled={saving}
                      className="flex items-center gap-1 rounded-md bg-[#3B62D9] px-2 py-1 text-[11px] font-medium text-white hover:bg-[#3451b8] disabled:opacity-60"
                    >
                      <Check size={12} /> {saving ? "Saving…" : "Save"}
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="space-y-3 px-4 py-3">
              {editing ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Name</div>
                      <input
                        className="w-full rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-[#3B62D9]"
                        value={draft.name}
                        onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                      />
                    </div>
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Active</div>
                      <select
                        className="w-full rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-[#3B62D9]"
                        value={draft.active}
                        onChange={(e) => setDraft((d) => ({ ...d, active: e.target.value }))}
                      >
                        <option value="true">Active</option>
                        <option value="false">Inactive</option>
                      </select>
                    </div>
                  </div>
                  <FieldBlock label="Description" value={t.description} editing draft={draft.description} onChange={(v) => setDraft((d) => ({ ...d, description: v }))} />
                </>
              ) : (
                t.description ? <div className="text-[13px] text-muted-foreground">{t.description}</div> : null
              )}

              <FieldBlock label="Event Type" value={t.event_type} editing={editing} draft={draft.event_type ?? ""} onChange={(v) => setDraft((d) => ({ ...d, event_type: v }))} />
              <FieldBlock label="Conditions" value={t.conditions} editing={editing} draft={draft.conditions ?? ""} onChange={(v) => setDraft((d) => ({ ...d, conditions: v }))} />
              <FieldBlock label="Actions" value={t.actions} editing={editing} draft={draft.actions ?? ""} onChange={(v) => setDraft((d) => ({ ...d, actions: v }))} />

              {!editing && (
                <div className="text-[11px] text-muted-foreground">
                  Created by {t.created_by ?? "—"} · {t.created_at ?? ""}
                </div>
              )}

              {error && <div className="rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-600">{error}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
