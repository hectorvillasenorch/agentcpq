import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { createRelatedRecord, fetchRelatedFields, type RelatedFieldDef } from "../../lib/api";

interface Props {
  parentObject: string;
  parentId: string | number;
  parentLabel?: string;
  relatedObject: string;
  sectionLabel?: string;
  onClose: () => void;
  onCreated: (payload: unknown, message: string) => void;
}

const prettyType = (t: string) => (t || "text").toLowerCase();

/** Form to create a record of a related object, pre-linked to the open record. */
export function AddRelatedRecordModal({
  parentObject,
  parentId,
  parentLabel,
  relatedObject,
  sectionLabel,
  onClose,
  onCreated,
}: Props) {
  const [fields, setFields] = useState<RelatedFieldDef[]>([]);
  const [title, setTitle] = useState(sectionLabel || relatedObject);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRelatedFields(parentObject, relatedObject)
      .then((res) => {
        if (cancelled) return;
        if (res.error) {
          setError(res.error);
        } else {
          setFields((res.fields || []).filter((f) => !f.is_link));
          setTitle(res.label || sectionLabel || relatedObject);
        }
      })
      .catch(() => setError("Could not load the fields for this object."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [parentObject, relatedObject, sectionLabel]);

  const save = async () => {
    if (saving) return;
    const missing = fields.filter((f) => f.required && !(values[f.name] || "").trim()).map((f) => f.label || f.name);
    if (missing.length > 0) {
      setError(`Please fill: ${missing.join(", ")}`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await createRelatedRecord(parentObject, parentId, relatedObject, values);
      if (res.error) {
        setError(res.error);
      } else {
        onCreated(res.single_record, res.message || `${title} created.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the record.");
    } finally {
      setSaving(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-[#3B62D9]";
  const labelClass = "mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";

  const renderInput = (field: RelatedFieldDef) => {
    const value = values[field.name] || "";
    const set = (next: string) => setValues((prev) => ({ ...prev, [field.name]: next }));
    const dtype = prettyType(field.data_type);
    const options = (field.options || []).map((opt) =>
      typeof opt === "object" && opt !== null
        ? { value: String((opt as { value?: unknown }).value), label: String((opt as { label?: unknown }).label) }
        : { value: String(opt), label: String(opt) }
    );

    if (options.length > 0 || dtype === "dropdown" || dtype === "choice" || dtype === "boolean") {
      const opts = dtype === "boolean" && options.length === 0 ? [{ value: "true", label: "Yes" }, { value: "false", label: "No" }] : options;
      return (
        <select className={inputClass} value={value} onChange={(e) => set(e.target.value)}>
          <option value="">—</option>
          {opts.map((o, i) => (
            <option key={i} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    }
    if (dtype === "textarea" || dtype === "text_multiline") {
      return <textarea rows={2} className={`${inputClass} resize-y`} value={value} onChange={(e) => set(e.target.value)} />;
    }
    if (dtype === "date") return <input type="date" className={inputClass} value={value} onChange={(e) => set(e.target.value)} />;
    if (dtype === "datetime") return <input type="datetime-local" className={inputClass} value={value} onChange={(e) => set(e.target.value)} />;
    if (dtype === "number" || dtype === "decimal" || dtype === "currency") {
      return <input type="number" step="any" className={inputClass} value={value} onChange={(e) => set(e.target.value)} />;
    }
    if (dtype === "lookup") {
      // Lookup targets are set from the record form; here we accept the id/name directly.
      return (
        <input
          className={inputClass}
          value={value}
          placeholder="Search later in the record form"
          onChange={(e) => set(e.target.value)}
        />
      );
    }
    return <input type="text" className={inputClass} value={value} onChange={(e) => set(e.target.value)} />;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-white shadow-lg">
        <div className="flex items-center justify-between border-b border-[#EDEEF1] px-4 py-3">
          <span className="text-[13px] font-semibold text-foreground">
            New {title}
            {parentLabel ? <span className="font-normal text-muted-foreground"> · linked to {parentLabel}</span> : null}
          </span>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
            <X size={15} />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
              <Loader2 size={14} className="animate-spin" /> Loading fields…
            </div>
          ) : fields.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">No editable fields available for this object.</p>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
              {fields.map((field) => (
                <div key={field.name} className={prettyType(field.data_type) === "textarea" ? "col-span-2" : ""}>
                  <label className={labelClass}>
                    {field.label || field.name}
                    {field.required ? " *" : ""}
                  </label>
                  {renderInput(field)}
                </div>
              ))}
            </div>
          )}
          {error && <p className="mt-3 text-[12px] text-red-600">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#EDEEF1] px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border bg-white px-3 py-1.5 text-[12px] font-medium text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || loading}
            className="flex items-center gap-1.5 rounded-md bg-[#3B62D9] px-3 py-1.5 text-[12px] font-medium text-white hover:bg-[#3253bd] disabled:opacity-60"
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            Create {title}
          </button>
        </div>
      </div>
    </div>
  );
}
