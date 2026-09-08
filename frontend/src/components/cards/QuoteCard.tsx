/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { sendQuoteLineAction, searchProducts, refreshQuoteDetails, type ProductSuggestion } from "../../lib/api";
import { formatDate, formatDateTime } from "../../lib/format";

interface QuoteLineItem {
  id?: number | string;
  product?: string;
  sku?: string;
  quantity?: number | string;
  unit_price?: number | string;
  total_price?: number | string;
  discount_type?: string;
  discount_percentage?: number | string;
  discount_amount?: number | string;
  is_subscription?: boolean;
  term?: number | string;
  is_bundle_child?: boolean;
  bundle_name?: string;
  [key: string]: any;
}

export interface QuotePayload {
  quote_id?: number | string;
  quote_name?: string;
  account?: string;
  opportunity?: string;
  expiration_date?: string;
  created_at?: string;
  status?: string;
  status_value?: string;
  notes?: string;
  subtotal?: number | string;
  net_amount?: number | string;
  tax_amount?: number | string;
  tax_percentage?: number | string;
  discount_amount?: number | string;
  discount_percentage?: number | string;
  rendered_fields?: string[];
  line_items?: QuoteLineItem[];
  [key: string]: any;
}

function num(v: unknown): number {
  const n = parseFloat(String(v ?? "").replace(/[$%,]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function money(v: unknown): string {
  return num(v).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** Line total — matches the backend `QuoteLine.update_total_price()`:
 *  (unit_price − discount_per_unit) × quantity × (term if subscription),
 *  where discount_per_unit is the amount for "amount" type, else unit × pct/100. */
function calcLineTotal(line: QuoteLineItem): number {
  const qty = Math.max(0, num(line.quantity));
  const unit = num(line.unit_price);
  const discountType = String(line.discount_type || "").toLowerCase();
  const pctVal = num(line.discount_percentage);
  const amtVal = num(line.discount_amount);

  const discountPerUnit = discountType === "amount" && amtVal > 0 ? amtVal : (unit * pctVal) / 100;
  const unitNet = Math.max(0, unit - discountPerUnit);
  let total = unitNet * qty;
  if (line.is_subscription) {
    total *= num(line.term) || 1;
  }
  return total;
}

/** Raw string for the editable input (strips %/$ for discount fields). */
function cellValue(line: QuoteLineItem, field: string): string {
  const raw = line[field];
  if (field === "discount_percentage" || field === "discount_amount") {
    return String(raw ?? "").replace(/[%$]/g, "");
  }
  return raw === null || raw === undefined ? "" : String(raw);
}

/** Nested quote editor: header, meta, editable line items, live totals, notes. */
export default function QuoteCard({
  payload,
  sessionId,
}: {
  payload: QuotePayload;
  sessionId?: string | null;
}) {
  const [quote, setQuote] = useState<QuotePayload>(payload);
  const [items, setItems] = useState<QuoteLineItem[]>(payload.line_items || []);
  const [busy, setBusy] = useState(false);
  const [addInput, setAddInput] = useState("");
  const [suggestions, setSuggestions] = useState<ProductSuggestion[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);
  const searchTimer = useRef<number | undefined>(undefined);
  const syncTimers = useRef<Record<string, number>>({});

  const hasSubscription = items.some((i) => i.is_subscription);
  const status = quote.status_value || quote.status || "";

  // Live totals (recalculated on every keystroke). Exclude bundle children to
  // match the backend `get_subtotal_amount()`.
  const subtotal = items.filter((l) => !l.is_bundle_child).reduce((s, l) => s + calcLineTotal(l), 0);
  const quoteDiscountAmount = num(quote.discount_amount);
  const quoteDiscountPct = num(quote.discount_percentage);
  const quoteDiscount = quoteDiscountAmount > 0 ? quoteDiscountAmount : (subtotal * quoteDiscountPct) / 100;
  const tax = num(quote.tax_amount);
  const net = Math.max(0, subtotal - quoteDiscount + tax);

  const applyQuote = (q: QuotePayload) => {
    setQuote(q);
    setItems(q.line_items || []);
  };

  // If the Opportunity/Account behind this quote is renamed elsewhere, silently
  // refresh just the meta (never clobber in-progress line edits).
  useEffect(() => {
    const quoteId = payload.quote_id ?? quote.quote_id;
    if (quoteId == null) return;
    const oppId = quote.opportunity_id ?? payload.opportunity_id;
    const accId = quote.account_id ?? payload.account_id;
    const onChanged = (e: Event) => {
      const det = (e as CustomEvent).detail as { object?: string; id?: unknown } | undefined;
      if (!det) return;
      const changedThisQuote =
        (det.object === "Opportunity" && oppId != null && String(det.id) === String(oppId)) ||
        (det.object === "Account" && accId != null && String(det.id) === String(accId)) ||
        (det.object === "Quote" && String(det.id) === String(quoteId));
      if (!changedThisQuote) return;
      refreshQuoteDetails(quoteId).then((fresh) => {
        if (!fresh) return;
        const meta: Record<string, unknown> = {};
        for (const k of [
          "quote_name",
          "account",
          "account_id",
          "opportunity",
          "opportunity_id",
          "status",
          "status_value",
          "expiration_date",
          "created_at",
        ]) {
          if (fresh[k] !== undefined) meta[k] = fresh[k];
        }
        setQuote((prev) => ({ ...prev, ...meta }));
      });
    };
    window.addEventListener("cpq:record-changed", onChanged);
    return () => window.removeEventListener("cpq:record-changed", onChanged);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload.quote_id, payload.opportunity_id, payload.account_id]);

  const runAction = async (message: string) => {
    setBusy(true);
    setFeedback(null);
    try {
      const res = await sendQuoteLineAction(message, sessionId ?? undefined);
      if (res.quote) {
        applyQuote(res.quote as QuotePayload);
        setFeedback("Updated");
      } else {
        setFeedback(res.error || "Could not update the quote.");
      }
    } catch {
      setFeedback("Failed to update the quote.");
    } finally {
      setBusy(false);
    }
  };

  const removeLine = (line: QuoteLineItem) => {
    const sku = line.sku || line.product || "";
    if (!sku) return;
    const payload = { quote: quote.quote_name, sku, hiddenMessage: true };
    void runAction(`Delete Quote Line: ${JSON.stringify(payload)}`);
  };

  /** Optimistic field edit: update local state instantly, sync to server debounced. */
  const editLine = (line: QuoteLineItem, field: string, raw: string) => {
    setItems((prev) =>
      prev.map((l) => (l.id === line.id ? { ...l, [field]: raw } : l))
    );
    const key = `${line.id}:${field}`;
    window.clearTimeout(syncTimers.current[key]);
    syncTimers.current[key] = window.setTimeout(() => {
      const updateData = {
        quote: quote.quote_name,
        quote_line_id: line.id,
        sku: line.sku,
        field,
        value: num(raw),
        hiddenMessage: true,
      };
      sendQuoteLineAction(`Update Quote Line: ${JSON.stringify(updateData)}`, sessionId ?? undefined).then(
        (res) => {
          if (res.quote) applyQuote(res.quote as QuotePayload);
        }
      );
    }, 700);
  };

  const addLine = () => {
    const product = addInput.trim();
    if (!product) return;
    setAddInput("");
    setSuggestions([]);
    const payload = { quote: quote.quote_name, sku: product, quantity: 1, hiddenMessage: true };
    void runAction(`Add Product To Quote: ${JSON.stringify(payload)}`);
  };

  const handleAddInput = (v: string) => {
    setAddInput(v);
    window.clearTimeout(searchTimer.current);
    if (!v.trim()) {
      setSuggestions([]);
      return;
    }
    searchTimer.current = window.setTimeout(async () => {
      try {
        setSuggestions(await searchProducts(v));
      } catch {
        setSuggestions([]);
      }
    }, 250);
  };

  const addProduct = (p: ProductSuggestion) => {
    setAddInput("");
    setSuggestions([]);
    const payload = { quote: quote.quote_name, sku: p.sku, quantity: 1, hiddenMessage: true };
    void runAction(`Add Product To Quote: ${JSON.stringify(payload)}`);
  };

  const editableInput = (line: QuoteLineItem, field: string, width = "w-20") => (
    <input
      type="number"
      step="any"
      value={cellValue(line, field)}
      onChange={(e) => editLine(line, field, e.target.value)}
      className={`${width} rounded-md border border-[#E2E8F0] bg-white px-2 py-1 text-[13px] text-foreground outline-none focus:border-[#3B62D9]`}
    />
  );

  return (
    <div className="overflow-hidden rounded-lg border border-[#EDEEF1]">
      <div className="flex items-center gap-2 border-b border-[#EDEEF1] bg-[#F7F8FA] px-4 py-2.5">
        <span className="text-[13px] font-semibold text-foreground">{quote.quote_name || "Quote"}</span>
        {status && (
          <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {status}
          </span>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground">
          {busy ? "Saving…" : feedback || ""}
        </span>
      </div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3 border-b border-[#EDEEF1] px-4 py-3">
        {quote.account && (
          <div>
            <div className="text-[11px] text-muted-foreground">Account</div>
            <div className="text-[13px] text-foreground">{quote.account}</div>
          </div>
        )}
        {quote.opportunity && (
          <div>
            <div className="text-[11px] text-muted-foreground">Opportunity</div>
            <div className="text-[13px] text-foreground">{quote.opportunity}</div>
          </div>
        )}
        {quote.expiration_date && (
          <div>
            <div className="text-[11px] text-muted-foreground">Expiration</div>
            <div className="text-[13px] text-foreground">{formatDate(quote.expiration_date)}</div>
          </div>
        )}
        {quote.created_at && (
          <div>
            <div className="text-[11px] text-muted-foreground">Created</div>
            <div className="text-[13px] text-foreground">{formatDateTime(quote.created_at)}</div>
          </div>
        )}
      </div>

      {items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[14px]">
            <thead>
              <tr className="bg-[#F7F8FA]">
                <th className="whitespace-nowrap px-4 py-3 font-semibold text-foreground">Product</th>
                <th className="whitespace-nowrap px-4 py-3 font-semibold text-foreground">Qty</th>
                <th className="whitespace-nowrap px-4 py-3 font-semibold text-foreground">Unit Price</th>
                <th className="whitespace-nowrap px-4 py-3 font-semibold text-foreground">Discount %</th>
                <th className="whitespace-nowrap px-4 py-3 font-semibold text-foreground">Discount $</th>
                {hasSubscription && (
                  <th className="whitespace-nowrap px-4 py-3 font-semibold text-foreground">Term</th>
                )}
                <th className="whitespace-nowrap px-4 py-3 font-semibold text-foreground">Total</th>
                <th className="w-10 px-2 py-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => (
                <tr key={item.id ?? i} className="border-t border-[#EDEEF1]">
                  <td className="px-4 py-3 text-foreground">
                    <div className="text-[13px] font-medium">{item.product || "—"}</div>
                    {item.sku && <div className="text-[11px] text-muted-foreground">{item.sku}</div>}
                  </td>
                  <td className="px-4 py-3">{editableInput(item, "quantity")}</td>
                  <td className="px-4 py-3">{editableInput(item, "unit_price")}</td>
                  <td className="px-4 py-3">{editableInput(item, "discount_percentage", "w-16")}</td>
                  <td className="px-4 py-3">{editableInput(item, "discount_amount", "w-16")}</td>
                  {hasSubscription && (
                    <td className="px-4 py-3">
                      {item.is_subscription ? editableInput(item, "term", "w-16") : <span className="text-muted-foreground">—</span>}
                    </td>
                  )}
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-foreground">
                    {money(calcLineTotal(item))}
                  </td>
                  <td className="px-2 py-3">
                    <button
                      type="button"
                      onClick={() => removeLine(item)}
                      className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-[#FEE2E2] hover:text-[#ef4444]"
                      title="Remove line"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 py-6 text-[13px] text-muted-foreground">No line items yet.</p>
      )}

      <div className="relative border-t border-[#EDEEF1] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={addInput}
            onChange={(e) => handleAddInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addLine()}
            placeholder="Search a product to add…"
            className="flex-1 rounded-md border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[13px] text-foreground outline-none focus:border-[#3B62D9]"
          />
          <button
            type="button"
            onClick={addLine}
            disabled={busy || !addInput.trim()}
            className="flex items-center gap-1 rounded-md border border-border bg-white px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            <Plus size={14} />
            Add line
          </button>
        </div>
        {suggestions.length > 0 && (
          <div className="absolute left-4 right-4 top-full z-10 mt-1 max-h-64 overflow-y-auto rounded-md border border-[#EDEEF1] bg-white shadow-sm">
            {suggestions.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => addProduct(p)}
                className="flex w-full items-center gap-2 border-b border-[#F1F2F4] px-3 py-2 text-left last:border-0 hover:bg-[#F7F8FA]"
              >
                <span className="flex-1 truncate text-[13px] text-foreground">{p.name}</span>
                <span className="text-[11px] text-muted-foreground">{p.sku}</span>
                <span className="text-[12px] font-medium text-foreground">{money(p.price)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-[#EDEEF1] bg-[#F7F8FA] px-4 py-3 text-[13px]">
        <span className="text-foreground">
          Subtotal: <span className="font-semibold">{money(subtotal)}</span>
        </span>
        {quoteDiscount > 0 && (
          <span className="text-muted-foreground">
            Discount: <span className="font-medium">{money(quoteDiscount)}</span>
          </span>
        )}
        {tax > 0 && (
          <span className="text-muted-foreground">
            Tax: <span className="font-medium">{money(tax)}</span>
          </span>
        )}
        <span className="ml-auto text-foreground">
          Net Total: <span className="font-semibold">{money(net)}</span>
        </span>
      </div>

      {quote.notes && (
        <div className="border-t border-[#EDEEF1] px-4 py-3 text-[13px] text-foreground">{quote.notes}</div>
      )}
    </div>
  );
}
