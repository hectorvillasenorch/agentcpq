import type { ChatMessage, ChatResponse, ChatSession, ParsedCard } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.error || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function fetchSessions(): Promise<ChatSession[]> {
  const data = await request<{ sessions: ChatSession[] }>("/agents/api/sessions/");
  return data.sessions;
}

export async function fetchMessages(sessionId: string): Promise<ChatMessage[]> {
  const data = await request<{ messages: ChatMessage[] }>(
    `/agents/api/messages/?session_id=${encodeURIComponent(sessionId)}`
  );
  return data.messages;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await request<{ success: boolean }>(
    `/dashboard/chat/session/${encodeURIComponent(sessionId)}/delete/`,
    { method: "POST", body: JSON.stringify({}) }
  );
}

/** Fetch a single record's full form payload for the eye-icon "view details" action. */
export async function fetchSingleRecord(object: string, recordId: string | number): Promise<unknown> {
  const data = await request<{ single_record: unknown }>(
    `/cpq/single-record/?object=${encodeURIComponent(object)}&record_id=${encodeURIComponent(String(recordId))}`
  );
  return data.single_record;
}

export async function renameSession(sessionId: string, title: string): Promise<void> {
  await request<{ title: string }>(
    `/dashboard/chat/session/${encodeURIComponent(sessionId)}/title/`,
    { method: "POST", body: JSON.stringify({ title }) }
  );
}

export async function saveSingleRecordLayout(
  object: string,
  order: string[],
  hidden: string[]
): Promise<void> {
  await request("/agents/single-record-layout/", {
    method: "POST",
    body: JSON.stringify({ object, order, hidden }),
  });
}

/** Sends a quote-line action (edit / add / remove) via chat and returns the updated quote. */
export async function sendQuoteLineAction(
  message: string,
  sessionId?: string
): Promise<{ quote?: unknown; error?: string }> {
  const data = await request<ChatResponse>("/agents/chat/", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  let node: unknown = data.response;
  while (
    node &&
    typeof node === "object" &&
    !Array.isArray(node) &&
    !("message" in (node as Record<string, unknown>)) &&
    "response" in (node as Record<string, unknown>)
  ) {
    node = (node as Record<string, unknown>).response;
  }
  const r = (node && typeof node === "object" ? node : {}) as Record<string, unknown>;
  return {
    quote: r.quote_details ?? r.update_details ?? undefined,
    error: typeof r.message === "string" ? r.message : undefined,
  };
}

export interface ProductSuggestion {
  id: number;
  name: string;
  sku: string;
  price: string;
  is_subscription: boolean;
}

export async function searchProducts(query: string): Promise<ProductSuggestion[]> {
  if (!query.trim()) return [];
  const data = await request<{ products: ProductSuggestion[] }>(
    `/agents/api/search-products/?q=${encodeURIComponent(query)}`,
    { method: "GET" }
  );
  return Array.isArray(data.products) ? data.products : [];
}

export interface RecordSearchResult {
  value: string;
  label: string;
}

/** Search records of an object (lookup combobox in the single-record form). */
export async function searchRecords(object: string, query: string): Promise<RecordSearchResult[]> {
  if (!object || !query.trim()) return [];
  const data = await request<{ results?: RecordSearchResult[] }>(
    `/agents/api/search-records/?object=${encodeURIComponent(object)}&q=${encodeURIComponent(query)}&limit=8`,
    { method: "GET" }
  );
  return Array.isArray(data.results) ? data.results : [];
}

export interface ActionTriggerDetail {
  id?: string | number;
  name: string;
  description?: string;
  event_type?: unknown;
  conditions?: unknown;
  actions?: unknown;
  active?: boolean;
  created_by?: string;
  created_at?: string;
}

/** Update an ActionTrigger's JSON fields (name/description/event_type/conditions/actions/active). */
export async function saveActionTrigger(
  triggerId: string | number,
  data: Partial<ActionTriggerDetail>
): Promise<ActionTriggerDetail | null> {
  const res = await request<{ trigger?: ActionTriggerDetail }>(
    `/agents/api/action-trigger/${triggerId}/update/`,
    { method: "POST", body: JSON.stringify(data) }
  );
  return res.trigger ?? null;
}

export interface SingleRecordUpdateField {
  field: string;
  value: unknown;
  data_type?: string;
  is_custom?: boolean;
  field_id?: string | number;
}

export interface SingleRecordSaveResult {
  payload?: unknown;
  updatedFields?: string[];
  failedFields?: string[];
  message?: string;
}

/** Saves a single-record field change through the chat API (Update Record: …). */
export async function saveSingleRecordUpdate(
  object: string | undefined,
  recordId: string | number | undefined,
  updates: SingleRecordUpdateField[],
  sessionId?: string
): Promise<SingleRecordSaveResult> {
  if (!object || !recordId) throw new Error("Missing record information for this update.");
  const payload = { object, record_id: recordId, updates, hiddenMessage: true };
  const data = await request<ChatResponse>("/agents/chat/", {
    method: "POST",
    body: JSON.stringify({ message: `Update Record: ${JSON.stringify(payload)}`, session_id: sessionId }),
  });
  // Unwrap nested {response: …} wrappers to the result payload.
  let node: unknown = data.response;
  while (
    node &&
    typeof node === "object" &&
    !Array.isArray(node) &&
    !("message" in (node as Record<string, unknown>)) &&
    "response" in (node as Record<string, unknown>)
  ) {
    node = (node as Record<string, unknown>).response;
  }
  const r = (node && typeof node === "object" ? node : {}) as Record<string, unknown>;
  return {
    payload: r.single_record,
    updatedFields: Array.isArray(r.updated_fields) ? (r.updated_fields as string[]) : undefined,
    failedFields: Array.isArray(r.failed_fields) ? (r.failed_fields as string[]) : undefined,
    message: typeof r.message === "string" ? r.message : undefined,
  };
}

const RESPONSE_CARD_KEYS = [
  "single_record",
  "single_record_summary",
  "quote_details",
  "update_details",
  "retrieved_records",
  "intelligence_dashboard",
  "validation_rules_details",
  "rules",
  "email_alerts_details",
  "inclusion_rules_details",
  "action_triggers_details",
  "exclusion_rules_details",
  "openGraphicBuilder",
];

export interface SendResult {
  text: string;
  sessionId?: string;
  cards?: ParsedCard[];
}

/** Unwrap the backend's nested `{response: …}` payloads into a flat SendResult. */
function unwrapChatResponse(raw: unknown, fallbackSessionId?: string): SendResult {
  let payload: unknown = raw;
  let payloadSessionId: unknown = undefined;
  while (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const p = payload as Record<string, unknown>;
    if (typeof p.session_id === "string") payloadSessionId = p.session_id;
    if (typeof p.message === "string") break;
    if ("response" in p) {
      payload = p.response;
    } else {
      break;
    }
  }

  const sid = typeof payloadSessionId === "string" ? payloadSessionId : fallbackSessionId;

  if (typeof payload === "string") {
    return { text: payload, sessionId: sid };
  }

  if (payload && typeof payload === "object") {
    const p = payload as Record<string, unknown>;
    const text =
      (typeof p.message === "string" && p.message) ||
      (typeof p.response === "string" && p.response) ||
      (typeof p.session_summary === "string" && p.session_summary) ||
      "Done.";
    const cards: ParsedCard[] = [];
    for (const key of RESPONSE_CARD_KEYS) {
      const val = p[key];
      if (val !== undefined && val !== null) {
        let json: unknown = val;
        // Carry the object-label map (custom objects: "pov__c" → "POV") so the
        // table header can show the friendly label instead of the API name.
        if (key === "retrieved_records" && p.object_labels) {
          json = { ...(val as Record<string, unknown>), _object_labels: p.object_labels };
        }
        cards.push({ key: `${key}:`, json, prefix: "" });
      }
    }
    // Generated document (e.g. quote PDF) with a signed download URL.
    if (typeof p.download_url === "string" && p.download_url) {
      cards.push({
        key: "document:",
        json: { download_url: p.download_url, document_version: p.document_version },
        prefix: "",
      });
    }
    return { text, sessionId: sid, cards: cards.length ? cards : undefined };
  }

  return { text: String(payload), sessionId: sid };
}

export async function sendChat(
  message: string,
  sessionId?: string
): Promise<SendResult> {
  const data = await request<ChatResponse>("/agents/chat/", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  return unwrapChatResponse(data.response, sessionId);
}

export interface StreamHandlers {
  onToken?: (delta: string) => void;
  onRows?: (object: string, rows: unknown[]) => void;
  onDone?: (result: SendResult) => void;
  onError?: (message: string) => void;
}

/**
 * Sends a message over the SSE endpoint, streaming LLM tokens and list rows as
 * they are produced. Resolves with the final SendResult once the agent is done.
 */
export async function sendChatStream(
  message: string,
  sessionId: string | undefined,
  handlers: StreamHandlers
): Promise<SendResult> {
  const res = await fetch("/agents/chat/stream/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(text || "Stream request failed.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: SendResult = { text: "Done.", sessionId };

  const handleEvent = (event: string, data: string) => {
    if (!data) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(data);
    } catch {
      return;
    }
    if (event === "token") {
      handlers.onToken?.(typeof parsed.content === "string" ? parsed.content : "");
    } else if (event === "rows") {
      const object = typeof parsed.object === "string" ? parsed.object : "Records";
      const rows = Array.isArray(parsed.rows) ? parsed.rows : [];
      handlers.onRows?.(object, rows);
    } else if (event === "done") {
      final = unwrapChatResponse(parsed.response, sessionId);
      handlers.onDone?.(final);
    } else if (event === "error") {
      handlers.onError?.(typeof parsed.message === "string" ? parsed.message : "Something went wrong.");
    }
  };

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      handleEvent(event, data);
    }
  }

  return final;
}
