/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { CalendarPlus, Eye, Link2, Settings2, Table as TableIcon, Trash2 } from "lucide-react";
import { autoFormatDate } from "../../lib/format";
import SingleRecordCard from "./SingleRecordCard";
import { ListLayoutEditor } from "./ListLayoutEditor";
import { fetchListLayout, fetchSingleRecord } from "../../lib/api";

type Row = Record<string, any>;

/** Fields we hide from record tables (internal IDs / timestamps noise). */
const SKIP_COLUMNS = new Set(["id", "accid"]);

function isObjectRow(v: unknown): v is Row {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

/** Finds the array of record rows inside the payload, plus a friendly title. */
function findRecordRows(data: any): { rows: Row[]; title: string } {
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const knownKeys = ["records", "data", "items", "rows", "results"];
    for (const key of knownKeys) {
      const v = data[key];
      if (Array.isArray(v) && v.length > 0 && v.every(isObjectRow)) {
        return { rows: v, title: data.title || "Records" };
      }
    }
    // Object-name keys (Account, Lead, Opportunity, ...) whose value is a row array.
    for (const [key, value] of Object.entries(data)) {
      if (Array.isArray(value) && value.length > 0 && value.every(isObjectRow)) {
        return { rows: value as Row[], title: key };
      }
    }
  }
  if (Array.isArray(data) && data.length > 0 && data.every(isObjectRow)) {
    return { rows: data, title: "Records" };
  }
  return { rows: [], title: "Records" };
}

function label(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

const CURRENCY_FIELD = /(amount|price|value|total|revenue|forecast|sum|cost|net|subtotal|tax|discount|budget|fee|annual|arr|mrr)/i;

function isCurrencyField(name: string): boolean {
  return CURRENCY_FIELD.test(name);
}

function formatCurrency(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : parseFloat(String(v).replace(/[$,]/g, ""));
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function formatCell(v: any, key?: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  if (key && isCurrencyField(key)) return formatCurrency(v);
  return autoFormatDate(v);
}

function formatMetric(v: any, label?: string): string {
  if (label && isCurrencyField(label)) return formatCurrency(v);
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}

/** Finds a nested `{aggregate: {...}}` payload and returns its object + aggregate. */
function findAggregate(data: any): { object: string; agg: any } | null {
  if (data?.aggregate && typeof data.aggregate === "object") {
    return { object: data.object || "Metric", agg: data.aggregate };
  }
  if (data && typeof data === "object" && !Array.isArray(data)) {
    for (const [key, val] of Object.entries(data)) {
      if (val && typeof val === "object" && !Array.isArray(val) && (val as any).aggregate) {
        return { object: key, agg: (val as any).aggregate };
      }
    }
  }
  return null;
}

function SeriesChart({ series, currency }: { series: any[]; currency: boolean }) {
  const points = series
    .filter((p) => p && p.period !== undefined && p.value !== undefined && p.value !== null)
    .slice(-24);
  if (points.length === 0) return null;
  const max = Math.max(...points.map((p) => Number(p.value) || 0), 0);
  const label = (p: any) => {
    const raw = String(p.period ?? "");
    const m = raw.match(/^(\d{4})-(\d{2})/);
    if (m) {
      const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const short = months[parseInt(m[2], 10) - 1] ?? m[2];
      return raw.length <= 7 ? short : `${short} ${String(m[1]).slice(2)}`;
    }
    return raw;
  };
  const val = (v: any) => (currency ? formatCurrency(v) : String(v));
  return (
    <div className="mt-3">
      <div className="flex items-end gap-1" style={{ height: 140 }}>
        {points.map((p, i) => {
          const h = max > 0 ? Math.max(4, Math.round((Number(p.value) / max) * 100)) : 4;
          return (
            <div key={i} className="flex h-full flex-1 flex-col justify-end" title={`${label(p)}: ${val(p.value)}`}>
              <div
                className="mx-auto w-full max-w-[38px] rounded-t bg-[#3B62D9]/85 transition-colors hover:bg-[#3B62D9]"
                style={{ height: `${h}%`, minHeight: 3 }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1">
        {points.map((p, i) => (
          <div key={i} className="flex-1 truncate text-center text-[10px] leading-tight text-muted-foreground">
            {label(p)}
          </div>
        ))}
      </div>
    </div>
  );
}

function AggregateCard({ object, agg }: { object: string; agg: any }) {
  const field = String(agg.field || "").replace(/^_/, "").replace(/_/g, " ");
  const fn = String(agg.function || "value").toLowerCase();
  const range = String(agg.range || "").replace(/_/g, " ");
  const value = agg.value ?? agg.total ?? agg.count ?? "—";
  const series = Array.isArray(agg.series) && agg.series.length > 0 ? agg.series : null;
  const isCurrency = isCurrencyField(field) || fn === "sum" || fn === "avg" || fn === "average";
  return (
    <div className="overflow-hidden rounded-lg border border-[#EDEEF1]">
      <div className="flex items-center gap-1.5 border-b border-[#EDEEF1] px-4 py-2 text-[12px] font-medium text-muted-foreground">
        <TableIcon size={13} />
        {object}
      </div>
      <div className="px-4 py-3 text-[13px] text-foreground">
        <span className="text-[20px] font-semibold">{formatMetric(value, field)}</span>
        <span className="ml-2 text-muted-foreground">
          {fn} of {field || "records"}
          {range ? ` · ${range}` : ""}
        </span>
        {series && <SeriesChart series={series} currency={isCurrency} />}
      </div>
    </div>
  );
}

/** Nested table block for `retrieved_records` — a clean table, never raw JSON. */
export default function RecordsTable({
  payload,
  sessionId,
  onSendMessage,
}: {
  payload: unknown;
  sessionId?: string | null;
  onSendMessage?: (text: string) => void;
}) {
  const data = (payload || {}) as any;
  const [expanded, setExpanded] = useState<{ object: string; record: unknown } | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [listLayout, setListLayout] = useState<{ order: string[]; hidden: string[] }>({ order: [], hidden: [] });
  const [showListLayout, setShowListLayout] = useState(false);

  const metrics: any[] = Array.isArray(data?.metrics) ? data.metrics : [];
  if (metrics.length > 0) {
    return (
      <div className="overflow-hidden rounded-lg border border-[#EDEEF1]">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-px bg-[#EDEEF1] p-px">
          {metrics.map((m, i) => (
            <div key={i} className="bg-white p-3">
              <div className="text-[12px] text-muted-foreground">
                {m.label || m.title || "Metric"}
              </div>
              <div className="mt-0.5 text-[16px] font-semibold text-foreground">
                {formatMetric(m.value ?? m.total ?? m.count ?? "—", m.label || m.title)}
              </div>
              {m.insight && (
                <div className="mt-1 text-[12px] text-muted-foreground">{m.insight}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  const { rows, title } = findRecordRows(data);
  if (rows.length === 0) {
    const agg = findAggregate(data);
    if (agg) return <AggregateCard object={agg.object} agg={agg.agg} />;
    return <JsonFallback payload={data} />;
  }

  const baseColumns = Object.keys(rows[0]).filter(
    (k) => !k.startsWith("_") && !SKIP_COLUMNS.has(k) && !k.endsWith("_id")
  );
  // Apply the user's saved column layout (order + hidden) for this object.
  const orderIndex = new Map(listLayout.order.map((k, i) => [k, i]));
  const columns = [...baseColumns]
    .filter((k) => !listLayout.hidden.includes(k))
    .sort((a, b) => {
      const ai = orderIndex.get(a);
      const bi = orderIndex.get(b);
      if (ai === undefined && bi === undefined) return 0;
      if (ai === undefined) return 1;
      if (bi === undefined) return -1;
      return ai - bi;
    });
  if (columns.length === 0) {
    return <JsonFallback payload={data} />;
  }

  // Load the saved list layout whenever this card's object changes.
  useEffect(() => {
    let cancelled = false;
    fetchListLayout(title)
      .then((res) => {
        if (!cancelled) setListLayout({ order: res.order || [], hidden: res.hidden || [] });
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, [title]);

  const rowId = (row: Row): string | number | null | undefined =>
    (row.id ?? row.record_id ?? row.pkid) as string | number | null | undefined;

  // Custom objects come through with their API name as the key ("pov__c"); prefer
  // the friendly label the backend sends in _object_labels for the header.
  const displayTitle = ((data?._object_labels as Record<string, unknown> | undefined)?.[title] as string) || title;

  const viewRecord = async (object: string, row: Row) => {
    const id = rowId(row);
    if (id === undefined || id === null) return;
    const key = `${object}:${id}`;
    setLoadingId(key);
    try {
      const record = await fetchSingleRecord(object, id);
      if (record) setExpanded({ object, record });
    } catch {
      /* non-fatal */
    } finally {
      setLoadingId(null);
    }
  };

  // Best display name for a row (used by the chat actions).
  const rowName = (row: Row): string => {
    for (const c of columns) {
      const v = row[c];
      if (v !== null && v !== undefined && String(v) !== "") return String(v);
    }
    return "";
  };

  const runAction = (msg: string) => {
    if (onSendMessage) onSendMessage(msg);
  };

  return (
    <div className="overflow-hidden rounded-lg border border-[#EDEEF1]">
      <div className="flex items-center gap-1.5 border-b border-[#EDEEF1] px-4 py-2 text-[12px] font-medium text-muted-foreground">
        <TableIcon size={13} />
        <span className="truncate">
          {displayTitle} · {rows.length}
        </span>
        <button
          type="button"
          onClick={() => setShowListLayout(true)}
          className="ml-auto flex shrink-0 items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground"
          title={`Edit ${displayTitle} list columns`}
        >
          <Settings2 size={13} />
          Layout
        </button>
      </div>

      {showListLayout && (
        <ListLayoutEditor
          object={title}
          columns={baseColumns}
          initialOrder={listLayout.order}
          initialHidden={listLayout.hidden}
          onClose={() => setShowListLayout(false)}
          onSaved={(order: string[], hidden: string[]) => setListLayout({ order, hidden })}
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[14px]">
          <thead>
            <tr className="bg-[#F7F8FA]">
              <th className="w-28 px-3 py-3" />
              {columns.map((c) => (
                <th
                  key={c}
                  className="whitespace-nowrap px-4 py-3 font-semibold text-foreground"
                >
                  {label(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const id = rowId(row);
              const loading = loadingId === `${title}:${id}`;
              return (
                <tr key={i} className="border-t border-[#EDEEF1]">
                  <td className="px-3 py-3">
                    {id != null && (
                      <div className="flex items-center gap-0.5">
                        <button
                          type="button"
                          onClick={() => viewRecord(title, row)}
                          disabled={loading}
                          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                          title="View record"
                          aria-label="View record"
                        >
                          <Eye size={15} />
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            runAction(`create an activity for ${displayTitle} ${rowName(row)}`)
                          }
                          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          title="Create activity"
                          aria-label="Create activity"
                        >
                          <CalendarPlus size={15} />
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            runAction(`show related records for ${displayTitle} ${rowName(row)}`)
                          }
                          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          title="Related records"
                          aria-label="Related records"
                        >
                          <Link2 size={15} />
                        </button>
                        <button
                          type="button"
                          onClick={() => runAction(`delete ${displayTitle} ${rowName(row)}`)}
                          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600"
                          title="Delete record"
                          aria-label="Delete record"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    )}
                  </td>
                  {columns.map((c) => {
                    const cellText = formatCell(row[c], c);
                    const isStageColumn = c.toLowerCase().includes("stage");
                    let cellClass = "whitespace-nowrap px-4 py-3 text-foreground";
                    if (isStageColumn && cellText.trim() === "Closed Won") {
                      cellClass += " font-semibold text-green-600";
                    } else if (isStageColumn && cellText.trim() === "Closed Lost") {
                      cellClass += " font-semibold text-red-600";
                    }
                    return (
                      <td key={c} className={cellClass}>
                        {cellText}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {expanded && (
        <div className="border-t border-[#EDEEF1] p-3">
          <SingleRecordCard
            key={`${expanded.object}:${(expanded.record as { record_id?: string | number } | null)?.record_id ?? "new"}`}
            payload={expanded.record as never}
            sessionId={sessionId}
          />
        </div>
      )}
    </div>
  );
}

function JsonFallback({ payload }: { payload: unknown }) {
  const text = JSON.stringify(payload, null, 2);
  return (
    <div className="overflow-hidden rounded-lg border border-[#EDEEF1]">
      <div className="border-b border-[#EDEEF1] px-4 py-2 text-[12px] font-medium text-muted-foreground">
        Details
      </div>
      <pre className="max-h-80 overflow-auto p-4 text-[12px] leading-relaxed text-foreground">
        {text}
      </pre>
    </div>
  );
}
