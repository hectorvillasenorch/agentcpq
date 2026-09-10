import { useState } from "react";
import { Loader2, X } from "lucide-react";
import { createActivity } from "../../lib/api";

const ACTIVITY_TYPES = [
  { value: "call", label: "Call" },
  { value: "email", label: "Email" },
  { value: "meeting", label: "Meeting" },
  { value: "task", label: "Task" },
];

const STATUSES = [
  { value: "not_started", label: "Not Started" },
  { value: "in_progress", label: "In Progress" },
  { value: "completed", label: "Completed" },
  { value: "deferred", label: "Deferred" },
];

interface Props {
  object: string;
  recordId: string | number;
  recordLabel?: string;
  onCancel: () => void;
  onCreated: (payload: unknown, message: string) => void;
}

/** Inline "log an activity" form shown under the record header in the chat form card. */
export function ActivityQuickForm({ object, recordId, recordLabel, onCancel, onCreated }: Props) {
  const [subject, setSubject] = useState("");
  const [activityType, setActivityType] = useState("call");
  const [status, setStatus] = useState("not_started");
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!subject.trim()) {
      setError("Add a subject, e.g. \"Follow up call\".");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await createActivity(object, recordId, {
        subject: subject.trim(),
        activity_type: activityType,
        status,
        due_date: dueDate || undefined,
        notes: notes.trim() || undefined,
      });
      if (res.error) {
        setError(res.error);
      } else {
        onCreated(res.single_record, res.message || "Activity created.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the activity.");
    } finally {
      setSaving(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-border bg-white px-2 py-1.5 text-[13px] text-foreground outline-none focus:border-[#3B62D9]";
  const labelClass = "mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";

  return (
    <div className="border-b border-[#EDEEF1] bg-[#FBFCFD] px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[12px] font-semibold text-foreground">
          Log activity{recordLabel ? ` for ${recordLabel}` : ""}
        </span>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md p-1 text-muted-foreground hover:text-foreground"
          title="Close"
        >
          <X size={14} />
        </button>
      </div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
        <div className="col-span-2">
          <label className={labelClass}>Subject</label>
          <input
            className={inputClass}
            value={subject}
            autoFocus
            placeholder="Follow up call"
            onChange={(e) => setSubject(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
            }}
          />
        </div>
        <div>
          <label className={labelClass}>Type</label>
          <select className={inputClass} value={activityType} onChange={(e) => setActivityType(e.target.value)}>
            {ACTIVITY_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Status</label>
          <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Due date</label>
          <input
            type="date"
            className={inputClass}
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </div>
        <div className="col-span-2">
          <label className={labelClass}>Notes</label>
          <textarea
            className={`${inputClass} min-h-[56px] resize-y`}
            value={notes}
            placeholder="Optional notes…"
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      </div>

      {error && <p className="mt-2 text-[12px] text-red-600">{error}</p>}

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="flex items-center gap-1.5 rounded-md bg-[#3B62D9] px-3 py-1.5 text-[12px] font-medium text-white hover:bg-[#3253bd] disabled:opacity-60"
        >
          {saving && <Loader2 size={13} className="animate-spin" />}
          Save activity
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-border bg-white px-3 py-1.5 text-[12px] font-medium text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
