import { useState } from "react";
import { ChevronDown, ChevronUp, Eye, EyeOff, X } from "lucide-react";
import { saveListLayout } from "../../lib/api";

interface Props {
  object: string;
  columns: string[];
  initialOrder: string[];
  initialHidden: string[];
  onClose: () => void;
  onSaved: (order: string[], hidden: string[]) => void;
}

const pretty = (key: string) => key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());

/** Column layout editor for list/table cards (reorder + hide columns, per user per object). */
export function ListLayoutEditor({
  object,
  columns,
  initialOrder,
  initialHidden,
  onClose,
  onSaved,
}: Props) {
  const startOrder = [
    ...initialOrder.filter((c) => columns.includes(c)),
    ...columns.filter((c) => !initialOrder.includes(c)),
  ];
  const [order, setOrder] = useState<string[]>(startOrder);
  const [hidden, setHidden] = useState<string[]>(initialHidden);
  const [saving, setSaving] = useState(false);

  const move = (index: number, delta: number) => {
    const next = [...order];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
  };

  const toggle = (key: string) => {
    setHidden((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  };

  const save = async () => {
    setSaving(true);
    try {
      await saveListLayout(object, order, hidden);
      onSaved(order, hidden);
      onClose();
    } catch {
      /* non-fatal */
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md overflow-hidden rounded-xl border border-border bg-white shadow-lg">
        <div className="flex items-center justify-between border-b border-[#EDEEF1] px-4 py-3">
          <span className="text-[13px] font-semibold text-foreground">
            {pretty(object)} list columns
          </span>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
            <X size={15} />
          </button>
        </div>

        <div className="max-h-[55vh] overflow-y-auto p-2">
          {order.map((key, i) => {
            const isHidden = hidden.includes(key);
            return (
              <div key={key} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-[#F7F8FA]">
                <span className={`flex-1 text-[13px] ${isHidden ? "text-muted-foreground line-through" : "text-foreground"}`}>
                  {pretty(key)}
                </span>
                <button type="button" onClick={() => move(i, -1)} className="rounded p-1 text-muted-foreground hover:text-foreground" title="Move up">
                  <ChevronUp size={14} />
                </button>
                <button type="button" onClick={() => move(i, 1)} className="rounded p-1 text-muted-foreground hover:text-foreground" title="Move down">
                  <ChevronDown size={14} />
                </button>
                <button type="button" onClick={() => toggle(key)} className="rounded p-1 text-muted-foreground hover:text-foreground" title={isHidden ? "Show" : "Hide"}>
                  {isHidden ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            );
          })}
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
            disabled={saving}
            className="rounded-md bg-[#3B62D9] px-3 py-1.5 text-[12px] font-medium text-white hover:bg-[#3253bd] disabled:opacity-60"
          >
            Save layout
          </button>
        </div>
      </div>
    </div>
  );
}
