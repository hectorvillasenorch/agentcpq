/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Archive,
  Box,
  Plus,
  Building2,
  CalendarPlus,
  Check,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  FileText,
  Link2,
  Loader2,
  Search,
  Settings2,
  Target,
  User,
  Users,
  X,
} from "lucide-react";
import {
  fetchSingleRecord,
  saveSingleRecordLayout,
  saveSingleRecordUpdate,
  searchRecords,
  dispatchRecordChanged,
  type RecordSearchResult,
} from "../../lib/api";
import { formatDate, formatDateTime } from "../../lib/format";
import { ActivityQuickForm } from "./ActivityQuickForm";
import { AddRelatedRecordModal } from "./AddRelatedRecordModal";

/** Objects an Activity can be linked to (Account links through its opportunity/contact). */
const ACTIVITY_RELATED_OBJECTS = new Set(["Lead", "Opportunity", "Contact", "Account"]);

interface RecordField {
  name?: string;
  label?: string;
  value?: unknown;
  display_value?: unknown;
  raw_value?: unknown;
  data_type?: string;
  is_editable?: boolean;
  is_multiline?: boolean;
  is_custom?: boolean;
  field_id?: string | number;
  options?: Array<string | { value: unknown; label: string }>;
  /** Target object of a lookup field, e.g. "Account" — enables the search combobox. */
  lookup_target?: string;
}

export interface SingleRecordPayload {
  object?: string;
  display_label?: string;
  record_value?: unknown;
  record_id?: string | number;
  fields?: RecordField[];
  is_custom_object?: boolean;
  can_delete?: boolean;
  layout?: { order?: string[]; hidden?: string[] };
  related?: RelatedRecordSection[];
}

export interface RelatedRecordSection {
  object?: string;
  label?: string;
  records?: RelatedRecordRow[];
  /** True for sections configured in Admin → Object Related Sections. */
  configured?: boolean;
}

export interface RelatedRecordRow {
  id?: string | number;
  name?: string;
  [key: string]: unknown;
}

function objectIcon(object?: string) {
  const o = (object || "").toLowerCase();
  if (o.includes("product")) return Box;
  if (o.includes("account")) return Building2;
  if (o.includes("contact")) return Users;
  if (o.includes("opportunity")) return Target;
  if (o.includes("lead")) return User;
  if (o.includes("quote")) return FileText;
  return Archive;
}

function fieldKey(field: RecordField): string {
  return `${field.name || ""}::${field.is_custom ? "custom" : "standard"}${
    field.is_custom && field.field_id ? "::" + field.field_id : ""
  }`;
}

/** The raw database primary key — hide it, show the friendly external ID instead. */
function isDbId(name?: string): boolean {
  return name?.toLowerCase() === "id";
}

/** System fields (external_id, accid, *_id, created_at, updated_at) — read-only, pinned to the bottom. */
function isSystemField(name?: string): boolean {
  if (!name) return false;
  const n = name.toLowerCase();
  return n.endsWith("_id") || n === "accid" || n === "created_at" || n === "updated_at";
}

function initialValue(field: RecordField): string {
  const v = field.raw_value ?? field.display_value ?? field.value;
  if (v === null || v === undefined || v === "") return "";
  return String(v);
}

type SaveStatus = "idle" | "saving" | "saved" | "error";

function EditableField({
  field,
  payload,
  sessionId,
  onSaved,
}: {
  field: RecordField;
  payload: SingleRecordPayload;
  sessionId?: string | null;
  onSaved?: () => void;
}) {
  const [value, setValue] = useState(initialValue(field));
  const [status, setStatus] = useState<SaveStatus>("idle");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  // React reuses the same field component when another record is opened (same field
  // name → same key), so the input would otherwise keep the previous record's value.
  useEffect(() => {
    if (status === "saving") return;
    setValue(initialValue(field));
  }, [field.name, field.raw_value, field.value, field.display_value, status]);

  const commit = (next: string) => {
    if (!payload.object || !payload.record_id) return;
    setStatus("saving");
    saveSingleRecordUpdate(
      payload.object,
      payload.record_id,
      [
        {
          field: field.name || "",
          value: next,
          data_type: field.data_type,
          is_custom: field.is_custom,
          field_id: field.field_id,
        },
      ],
      sessionId ?? undefined
    )
      .then((res) => {
        const ok = !(res.failedFields && res.failedFields.length);
        setStatus(ok ? "saved" : "error");
        window.setTimeout(() => setStatus((s) => (s === "saved" ? "idle" : s)), 1800);
        if (ok) onSaved?.();
      })
      .catch(() => setStatus("error"));
  };

  // Values are NOT saved while typing: we commit when the field loses focus
  // (blur) or when the user presses Enter. Selects save immediately on change.
  const lastCommitted = useRef(initialValue(field));
  const blurTimer = useRef<number | undefined>(undefined);
  const skipBlurCommit = useRef(false);

  const onChange = (next: string) => {
    setValue(next);
  };

  const commitIfChanged = (next: string) => {
    if (next === lastCommitted.current) return;
    lastCommitted.current = next;
    commit(next);
  };

  const onBlurCommit = () => {
    if (skipBlurCommit.current) {
      skipBlurCommit.current = false;
      return;
    }
    commitIfChanged(value);
  };

  const onSelect = (next: string) => {
    setValue(next);
    commitIfChanged(next);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    // Blur right after committing (the blur handler must not save again).
    skipBlurCommit.current = true;
    commitIfChanged(value);
    (event.target as HTMLElement).blur();
    window.clearTimeout(blurTimer.current);
    blurTimer.current = window.setTimeout(() => {
      skipBlurCommit.current = false;
    }, 300);
  };

  const dataType = (field.data_type || "text").toLowerCase();
  const inputClass =
    "w-full rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[13px] text-foreground outline-none transition-colors focus:border-[#3B62D9]";

  let control: React.ReactNode;
  if (dataType === "boolean") {
    control = (
      <select className={inputClass} value={value} onChange={(e) => onSelect(e.target.value)} onBlur={onBlurCommit}>
        <option value="">Unset</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  } else if (dataType === "date") {
    control = (
      <input type="date" className={inputClass} value={value} onChange={(e) => onChange(e.target.value)} onBlur={onBlurCommit} onKeyDown={onKeyDown} />
    );
  } else if (dataType === "datetime") {
    control = (
      <input
        type="datetime-local"
        className={inputClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlurCommit}
        onKeyDown={onKeyDown}
      />
    );
  } else if (dataType === "number") {
    control = (
      <input
        type="number"
        step="any"
        className={inputClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlurCommit}
        onKeyDown={onKeyDown}
      />
    );
  } else if (dataType === "lookup" && field.lookup_target) {
    // Lookup/relation fields get a search-as-you-type combobox (find the right
    // Account, Contact, Opportunity…) instead of a giant picklist dropdown.
    control = (
      <LookupFieldControl
        field={field}
        value={value}
        onChange={(next: string) => {
          setValue(next);
          commitIfChanged(next);
        }}
        inputClass={inputClass}
      />
    );
  } else if (
    dataType === "choice" ||
    dataType === "lookup" ||
    (Array.isArray(field.options) && field.options.length > 0)
  ) {
    control = (
      <select className={inputClass} value={value} onChange={(e) => onSelect(e.target.value)} onBlur={onBlurCommit}>
        <option value="">—</option>
        {(field.options || []).map((opt, i) => {
          // Options arrive as strings (picklist: ["Planned", "In Progress", …]) or
          // as {value, label} objects (lookups). Normalize both.
          const isObj = typeof opt === "object" && opt !== null;
          const optValue = isObj ? String((opt as { value?: unknown }).value) : String(opt);
          const optLabel = isObj ? String((opt as { label?: unknown }).label) : String(opt);
          return (
            <option key={i} value={optValue}>
              {optLabel}
            </option>
          );
        })}
      </select>
    );
  } else if (field.is_multiline) {
    control = (
      <textarea
        rows={3}
        className={`${inputClass} resize-y`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlurCommit}
        onKeyDown={onKeyDown}
      />
    );
  } else {
    control = (
      <input
        type="text"
        className={inputClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlurCommit}
        onKeyDown={onKeyDown}
      />
    );
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{field.label || field.name}</span>
        {status === "saving" && <span className="text-[10px] text-muted-foreground">Saving…</span>}
        {status === "saved" && (
          <span className="flex items-center gap-0.5 text-[10px] text-[#00c000]">
            <Check size={11} /> Saved
          </span>
        )}
        {status === "error" && <span className="text-[10px] text-[#ef4444]">Failed</span>}
      </div>
      {control}
    </div>
  );
}

function ReadOnlyValue({ field }: { field: RecordField }) {
  const dt = (field.data_type || "").toLowerCase();
  const raw = initialValue(field);
  const display =
    dt === "date" ? formatDate(raw) : dt === "datetime" || dt === "date_time" ? formatDateTime(raw) : raw;
  return (
    <div>
      <div className="mb-1 text-[11px] text-muted-foreground">{field.label || field.name}</div>
      <div className="break-words rounded-md border border-[#EDEEF1] bg-[#F7F8FA] px-2.5 py-2 text-[13px] text-foreground">
        {display || "—"}
      </div>
    </div>
  );
}

/** Search-as-you-type combobox for lookup/relation fields (e.g. Account, Contact). */
function LookupFieldControl({
  field,
  value,
  onChange,
  inputClass,
}: {
  field: RecordField;
  value: string;
  onChange: (next: string) => void;
  inputClass: string;
}) {
  const target = field.lookup_target || "";
  const resolveLabel = (v: string): string => {
    if (!v) return "";
    for (const opt of field.options || []) {
      if (opt && typeof opt === "object" && String(opt.value) === String(v)) return String(opt.label || "");
    }
    const disp = field.display_value ?? field.value;
    if (disp && String(disp) !== String(v)) return String(disp);
    return String(v);
  };

  const [text, setText] = useState<string>(resolveLabel(value));
  const [results, setResults] = useState<RecordSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const searchTimer = useRef<number | undefined>(undefined);
  const blurTimer = useRef<number | undefined>(undefined);
  const committedRef = useRef<string>(resolveLabel(value));

  useEffect(
    () => () => {
      window.clearTimeout(searchTimer.current);
      window.clearTimeout(blurTimer.current);
    },
    []
  );

  const runSearch = useCallback(
    (q: string) => {
      window.clearTimeout(searchTimer.current);
      if (!q.trim() || !target) {
        setResults([]);
        return;
      }
      setBusy(true);
      searchTimer.current = window.setTimeout(async () => {
        try {
          const rows = await searchRecords(target, q);
          setResults(rows);
        } catch {
          setResults([]);
        } finally {
          setBusy(false);
        }
      }, 280);
    },
    [target]
  );

  const onInput = (raw: string) => {
    setText(raw);
    setOpen(true);
    runSearch(raw);
  };

  const pick = (row: RecordSearchResult) => {
    committedRef.current = row.label;
    setText(row.label);
    setOpen(false);
    setResults([]);
    onChange(row.value);
  };

  const clearValue = () => {
    committedRef.current = "";
    setText("");
    setOpen(false);
    setResults([]);
    onChange("");
  };

  const onBlur = () => {
    window.clearTimeout(blurTimer.current);
    blurTimer.current = window.setTimeout(() => {
      setOpen(false);
      // Revert free-typed text to the last committed label (no accidental edits).
      setText(committedRef.current);
    }, 160);
  };

  return (
    <div className="relative">
      <div className="flex items-center rounded-md border border-[#E2E8F0] bg-white transition-colors focus-within:border-[#3B62D9]">
        <Search size={13} className="pointer-events-none ml-2 shrink-0 text-muted-foreground" />
        <input
          className="w-full bg-transparent px-2 py-1.5 text-[13px] text-foreground outline-none placeholder:text-muted-foreground"
          value={text}
          placeholder={`Search ${target || "records"}…`}
          onChange={(e) => onInput(e.target.value)}
          onFocus={() => setOpen(true)}
          onBlur={onBlur}
          autoComplete="off"
          spellCheck={false}
        />
        {value !== "" && (
          <button
            type="button"
            aria-label="Clear lookup"
            onClick={clearValue}
            onMouseDown={(e) => e.preventDefault()}
            className="mr-1 shrink-0 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X size={13} />
          </button>
        )}
      </div>
      {open && text.trim() !== "" && (
        <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-border bg-white py-1 shadow-lg">
          {busy && (
            <div className="flex items-center gap-2 px-3 py-2 text-[12px] text-muted-foreground">
              <Loader2 size={12} className="animate-spin" /> Searching…
            </div>
          )}
          {!busy && results.length === 0 && (
            <div className="px-3 py-2 text-[12px] text-muted-foreground">No matches found.</div>
          )}
          {!busy &&
            results.map((row, i) => (
              <button
                key={i}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(row);
                }}
                className="block w-full truncate px-3 py-1.5 text-left text-[13px] text-foreground hover:bg-muted"
              >
                {row.label}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

/** Simple reorder + hide modal for the single-record layout (admin only). */
function LayoutModal({
  object,
  fields,
  order,
  hidden,
  onClose,
  onSaved,
}: {
  object: string;
  fields: RecordField[];
  order: string[];
  hidden: string[];
  onClose: () => void;
  onSaved: (order: string[], hidden: string[]) => void;
}) {
  const [items, setItems] = useState<RecordField[]>(() => {
    const map = new Map(fields.map((f) => [fieldKey(f), f]));
    const ordered = order.map((k) => map.get(k)).filter(Boolean) as RecordField[];
    const rest = fields.filter((f) => !order.includes(fieldKey(f)));
    return [...ordered, ...rest];
  });
  const [hiddenSet, setHiddenSet] = useState<Set<string>>(new Set(hidden));
  const [saving, setSaving] = useState(false);

  const move = (index: number, dir: -1 | 1) => {
    setItems((prev) => {
      const next = [...prev];
      const target = index + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const toggle = (key: string) => {
    setHiddenSet((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    try {
      const newOrder = items.map(fieldKey);
      const newHidden = Array.from(hiddenSet);
      await saveSingleRecordLayout(object, newOrder, newHidden);
      onSaved(newOrder, newHidden);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[80vh] w-full max-w-md flex-col rounded-xl border border-border bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <span className="text-[14px] font-semibold text-foreground">
            Customize layout · {object}
          </span>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {items.map((f, i) => {
            const key = fieldKey(f);
            const isHidden = hiddenSet.has(key);
            return (
              <div
                key={key}
                className="mb-1 flex items-center gap-2 rounded-md border border-border px-2 py-1.5"
              >
                <span className={`flex-1 truncate text-[13px] ${isHidden ? "text-muted-foreground line-through" : "text-foreground"}`}>
                  {f.label || f.name}
                </span>
                <button
                  type="button"
                  onClick={() => move(i, -1)}
                  disabled={i === 0}
                  className="rounded p-0.5 text-muted-foreground hover:bg-muted disabled:opacity-30"
                >
                  <ChevronUp size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => move(i, 1)}
                  disabled={i === items.length - 1}
                  className="rounded p-0.5 text-muted-foreground hover:bg-muted disabled:opacity-30"
                >
                  <ChevronDown size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => toggle(key)}
                  className={`rounded p-0.5 ${isHidden ? "text-muted-foreground" : "text-[#3B62D9]"} hover:bg-muted`}
                  title={isHidden ? "Show" : "Hide"}
                >
                  {isHidden ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <button
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-[13px] text-foreground hover:bg-muted"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="rounded-md bg-primary px-3 py-1.5 text-[13px] font-medium text-primary-foreground disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RelatedRecords({
  sections,
  sessionId,
  isAdmin,
  depth = 0,
  ancestors = [],
  currentKey,
  onChildUpdated,
  onAdd,
}: {
  sections: RelatedRecordSection[];
  sessionId?: string | null;
  isAdmin?: boolean;
  depth?: number;
  ancestors?: Array<{ object?: string; id?: string | number }>;
  currentKey?: { object?: string; id?: string | number };
  onChildUpdated?: () => void;
  onAdd?: (object: string, label?: string) => void;
}) {
  const [expanded, setExpanded] = useState<{
    object: string;
    id: string | number;
    record: SingleRecordPayload | null;
  } | null>(null);

  const view = async (object: string, id: string | number) => {
    // If this record is already part of the visible chain (or is the current
    // record itself), scroll to it instead of nesting yet another copy.
    const isCurrent = !!currentKey && currentKey.object === object && String(currentKey.id) === String(id);
    const isAncestor = ancestors.some((a) => a.object === object && String(a.id) === String(id));
    if (isCurrent || isAncestor) {
      document
        .querySelector(`[data-record-key="${object}:${id}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setExpanded({ object, id, record: null });
    try {
      const record = await fetchSingleRecord(object, String(id));
      if (record) setExpanded({ object, id, record });
      else setExpanded(null);
    } catch {
      setExpanded(null);
    }
  };

  const CURRENCY_KEYS = new Set(["amount", "net", "unit_price", "line_total", "price", "total", "subtotal", "revenue"]);

  const fmt = (key: string, val: unknown) => {
    const s = String(val ?? "");
    if (CURRENCY_KEYS.has(key) && s !== "" && !Number.isNaN(Number(s))) {
      const n = Number(s);
      return n.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
        maximumFractionDigits: 2,
      });
    }
    return s;
  };

  return (
    <div className="mt-3 border-t border-[#EDEEF1] pt-3">
      <div className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold text-muted-foreground">
        <Link2 size={13} />
        Related records
      </div>
      <div className="space-y-3">
        {sections.map((sec) => (
          <div key={sec.object || sec.label} className="overflow-hidden rounded-lg border border-[#EDEEF1]">
            <div className="flex items-center gap-2 border-b border-[#EDEEF1] bg-[#F7F8FA] px-3 py-1.5 text-[12px] font-semibold text-foreground">
              <span className="truncate">
                {sec.label || sec.object} · {(sec.records || []).length}
              </span>
              {onAdd && sec.object && (
                <button
                  type="button"
                  onClick={() => onAdd(sec.object as string, sec.label)}
                  className="ml-auto flex shrink-0 items-center gap-1 rounded border border-border bg-white px-1.5 py-0.5 text-[11px] font-medium text-[#3B62D9] hover:bg-[#F3F6FE]"
                  title={`Add ${sec.label || sec.object}`}
                >
                  <Plus size={12} />
                  Add
                </button>
              )}
            </div>
            {(sec.records || []).length === 0 ? (
              <div className="px-3 py-2 text-[12px] text-muted-foreground">
                No {sec.label || sec.object} linked yet.
              </div>
            ) : (
            <table className="w-full text-left text-[13px]">
              <tbody>
                {(sec.records || []).map((row, i) => {
                  const cols = Object.keys(row).filter((k) => k !== "id" && k !== "name");
                  return (
                    <tr key={i} className="border-t border-[#EDEEF1]">
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          className="font-medium text-primary hover:underline"
                          onClick={() => {
                            if (sec.object && row.id != null) void view(sec.object, row.id);
                          }}
                        >
                          {String(row.name ?? "—")}
                        </button>
                      </td>
                      {cols.map((c) => {
                        const raw = row[c];
                        const text = fmt(c, raw);
                        const isUrl = typeof raw === "string" && /^https?:\/\//i.test(raw.trim());
                        return (
                          <td key={c} className="max-w-[320px] truncate px-3 py-2 text-muted-foreground">
                            {isUrl ? (
                              <a
                                href={raw.trim()}
                                target="_blank"
                                rel="noreferrer"
                                className="text-primary hover:underline"
                                title={raw.trim()}
                              >
                                {text}
                              </a>
                            ) : (
                              text
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            )}
          </div>
        ))}
      </div>
      {expanded && (
        <div className="mt-3">
          {expanded.record ? (
            <SingleRecordCard
              payload={expanded.record}
              sessionId={sessionId}
              isAdmin={isAdmin}
              depth={depth + 1}
              ancestors={currentKey ? [...ancestors, currentKey] : ancestors}
              onChildUpdated={onChildUpdated}
            />
          ) : (
            <div className="text-[12px] text-muted-foreground">Loading…</div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SingleRecordCard({
  payload,
  sessionId,
  isAdmin,
  depth = 0,
  ancestors = [],
  onChildUpdated,
}: {
  payload: SingleRecordPayload;
  sessionId?: string | null;
  isAdmin?: boolean;
  depth?: number;
  ancestors?: Array<{ object?: string; id?: string | number }>;
  onChildUpdated?: () => void;
}) {
  // Live payload — re-fetched after local/child edits so labels (e.g. the quote's
  // Opportunity name) never stay stale when a related record was renamed.
  const [live, setLive] = useState<SingleRecordPayload>(payload);
  useEffect(() => setLive(payload), [payload]);

  const refreshSelf = useCallback(() => {
    const obj = payload.object;
    const rid = payload.record_id;
    if (!obj || rid === undefined || rid === null || String(rid) === "") return;
    fetchSingleRecord(obj, String(rid))
      .then((r) => {
        if (r) setLive(r as SingleRecordPayload);
      })
      .catch(() => {});
  }, [payload.object, payload.record_id]);

  // A record changed somewhere under (or inside) this card → refresh this card,
  // notify ancestors, and broadcast so other open cards (e.g. a quote editor)
  // can update too.
  const notifyChanged = useCallback(() => {
    refreshSelf();
    if (payload.object && payload.record_id != null) {
      dispatchRecordChanged(payload.object, payload.record_id);
    }
    onChildUpdated?.();
  }, [refreshSelf, payload.object, payload.record_id, onChildUpdated]);

  const Icon = objectIcon(live.object);
  const title = live.record_value != null ? String(live.record_value) : "Record";
  const eyebrow = live.display_label || live.object || "Record";
  const recordKey = `${live.object ?? ""}:${live.record_id ?? ""}`;

  const [layout, setLayout] = useState<{ order: string[]; hidden: string[] }>({
    order: payload.layout?.order || [],
    hidden: payload.layout?.hidden || [],
  });
  const [showLayout, setShowLayout] = useState(false);
  const [showActivityForm, setShowActivityForm] = useState(false);
  const [createdActivity, setCreatedActivity] = useState<unknown>(null);
  const [activityToast, setActivityToast] = useState<string>("");
  const [addRelated, setAddRelated] = useState<{ object: string; label?: string } | null>(null);
  const [showAddMenu, setShowAddMenu] = useState(false);

  const hiddenSet = new Set(layout.hidden);
  const allFields = (live.fields || []).filter((f) => !isDbId(f.name) && !hiddenSet.has(fieldKey(f)));

  const orderIndex = new Map(layout.order.map((k, i) => [k, i]));
  const sorted = [...allFields].sort((a, b) => {
    const ai = orderIndex.get(fieldKey(a));
    const bi = orderIndex.get(fieldKey(b));
    if (ai === undefined && bi === undefined) return 0;
    if (ai === undefined) return 1;
    if (bi === undefined) return -1;
    return ai - bi;
  });

  const normalFields = sorted.filter((f) => !isSystemField(f.name));
  const systemFields = sorted.filter((f) => isSystemField(f.name));

  const renderField = (field: RecordField, i: number) => {
    const readOnly = field.is_editable === false || isSystemField(field.name);
    if (readOnly) return <ReadOnlyValue key={fieldKey(field) || i} field={field} />;
    return (
      <EditableField
        key={fieldKey(field) || i}
        field={field}
        payload={live}
        sessionId={sessionId}
        onSaved={notifyChanged}
      />
    );
  };

  return (
    <div data-record-key={recordKey} className="overflow-hidden rounded-lg border border-[#EDEEF1]">
      <div className="flex items-center gap-2 border-b border-[#EDEEF1] bg-[#F7F8FA] px-4 py-2.5">
        <Icon size={14} className="shrink-0 text-muted-foreground" />
        <span className="min-w-0 truncate text-[13px] font-medium text-foreground">
          <span className="font-semibold">{eyebrow}</span>
          <span className="mr-1 text-muted-foreground">:</span>
          <span>{title}</span>
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {ACTIVITY_RELATED_OBJECTS.has(String(live.object || "")) && !showActivityForm && (
            <button
              type="button"
              onClick={() => setShowActivityForm(true)}
              className="flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-[11px] font-medium text-[#3B62D9] hover:bg-[#F3F6FE]"
              title="Log an activity on this record"
            >
              <CalendarPlus size={13} />
              Log activity
            </button>
          )}
          {(live.related || []).length > 0 && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowAddMenu((v) => !v)}
                className="flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-[11px] font-medium text-[#3B62D9] hover:bg-[#F3F6FE]"
                title="Add a related record to this one"
              >
                <Plus size={13} />
                Add related
              </button>
              {showAddMenu && (
                <div className="absolute right-0 z-30 mt-1 w-56 overflow-hidden rounded-md border border-border bg-white py-1 shadow-lg">
                  {(live.related || []).map((sec) => (
                    <button
                      key={sec.object || sec.label}
                      type="button"
                      onClick={() => {
                        setShowAddMenu(false);
                        if (sec.object) setAddRelated({ object: sec.object, label: sec.label });
                      }}
                      className="block w-full truncate px-3 py-1.5 text-left text-[12px] text-foreground hover:bg-[#F7F8FA]"
                    >
                      {sec.label || sec.object}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={() => setShowLayout(true)}
            className="flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground"
            title="Edit this object's form layout"
          >
            <Settings2 size={13} />
            Layout
          </button>
        </div>
      </div>

      {showActivityForm && live.record_id != null && (
        <ActivityQuickForm
          object={String(live.object || "")}
          recordId={live.record_id as string | number}
          recordLabel={title}
          onCancel={() => setShowActivityForm(false)}
          onCreated={(payload, message) => {
            setShowActivityForm(false);
            setCreatedActivity(payload);
            setActivityToast(message);
          }}
        />
      )}

      {addRelated && live.record_id != null && (
        <AddRelatedRecordModal
          parentObject={String(live.object || "")}
          parentId={live.record_id as string | number}
          parentLabel={title}
          relatedObject={addRelated.object}
          sectionLabel={addRelated.label}
          onClose={() => setAddRelated(null)}
          onCreated={(payload, message) => {
            setAddRelated(null);
            setCreatedActivity(payload);
            setActivityToast(message);
            refreshSelf();
          }}
        />
      )}

      {activityToast && (
        <div className="border-b border-[#EDEEF1] bg-[#F0FDF4] px-4 py-2 text-[12px] text-[#166534]">
          {activityToast}
        </div>
      )}

      <div className="p-4">
        {normalFields.length === 0 && systemFields.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">No details available.</p>
        ) : (
          <>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
              {normalFields.map(renderField)}
            </div>
            {systemFields.length > 0 && (
              <div className="mt-3 border-t border-[#EDEEF1] pt-3">
                <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
                  {systemFields.map(renderField)}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {createdActivity ? (
        <div className="px-4 pb-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Activity just logged
          </div>
          <SingleRecordCard
            payload={createdActivity as SingleRecordPayload}
            sessionId={sessionId}
            isAdmin={isAdmin}
            depth={depth + 1}
            ancestors={recordKey ? [...ancestors, { object: live.object, id: live.record_id }] : ancestors}
          />
        </div>
      ) : null}

      {live.related && live.related.length > 0 && depth < 2 && (
        <div className="px-4 pb-4">
          <RelatedRecords
            sections={live.related}
            sessionId={sessionId}
            isAdmin={isAdmin}
            ancestors={ancestors}
            currentKey={{ object: live.object, id: live.record_id }}
            onChildUpdated={notifyChanged}
          />
        </div>
      )}

      {showLayout && (
        <LayoutModal
          object={live.object || "Record"}
          fields={live.fields || []}
          order={layout.order}
          hidden={layout.hidden}
          onClose={() => setShowLayout(false)}
          onSaved={(order, hidden) => setLayout({ order, hidden })}
        />
      )}
    </div>
  );
}
