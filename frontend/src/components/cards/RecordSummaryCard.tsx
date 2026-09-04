import { useState } from "react";
import { Eye } from "lucide-react";
import { fetchSingleRecord } from "../../lib/api";
import SingleRecordCard, { type SingleRecordPayload } from "./SingleRecordCard";

export interface RecordSummaryPayload {
  object?: string;
  record_id?: string | number;
  name?: string;
}

/**
 * Compact text-summary card (the details text is in the agent message).
 * Shows an eye icon that expands the full editable record form inline.
 */
export default function RecordSummaryCard({
  payload,
  sessionId,
}: {
  payload: RecordSummaryPayload;
  sessionId?: string | null;
}) {
  const [expanded, setExpanded] = useState<SingleRecordPayload | null>(null);
  const [loading, setLoading] = useState(false);

  const view = async () => {
    if (!payload.object || payload.record_id == null) return;
    setLoading(true);
    try {
      const record = await fetchSingleRecord(payload.object, String(payload.record_id));
      setExpanded(record ?? null);
    } catch {
      setExpanded(null);
    } finally {
      setLoading(false);
    }
  };

  if (expanded) {
    return <SingleRecordCard payload={expanded} sessionId={sessionId} />;
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => void view()}
        disabled={loading}
        className="flex items-center gap-1.5 rounded-md border border-border bg-white px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
        title="View full form"
      >
        <Eye size={14} />
        {loading ? "Loading…" : "View full form"}
      </button>
    </div>
  );
}
