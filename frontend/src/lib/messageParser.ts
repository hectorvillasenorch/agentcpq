import type { ParsedCard } from "./types";

const CARD_KEYS = [
  "quote_details:",
  "update_details:",
  "intelligence_dashboard:",
  "single_record:",
  "single_record_summary:",
  "validation_rules_details:",
  "rules:",
  "email_alerts_details:",
  "retrieved_records:",
  "inclusion_rules_details:",
  "action_triggers_details:",
  "exclusion_rules_details",
  "openGraphicBuilder",
];

/** Returns the balanced JSON substring starting at the first `{` or `[`. */
export function extractJson(text: string): string | null {
  const startObj = text.indexOf("{");
  const startArr = text.indexOf("[");
  let start = -1;
  if (startObj === -1) start = startArr;
  else if (startArr === -1) start = startObj;
  else start = Math.min(startObj, startArr);
  if (start === -1) return null;

  const open = text[start];
  const close = open === "{" ? "}" : "]";
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === open) depth++;
    else if (ch === close) {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

export function unescapeUnicode(str: string): string {
  return str.replace(/\\u[\dA-F]{4}/gi, (match) =>
    String.fromCharCode(parseInt(match.replace(/\\u/g, ""), 16))
  );
}

/** Removes trailing "key: {...}" (and "📦 llm: {...}") JSON dumps from a message. */
export function stripStructuredTail(text: string): string {
  const match =
    /[\s]*(?:📦\s*)?(?:single_record|single_record_summary|retrieved_records|quote_details|update_details|intelligence_dashboard|object_labels|validation_rules_details|rules|email_alerts_details|inclusion_rules_details|action_triggers_details|exclusion_rules_details|openGraphicBuilder|llm|download_url|document_version)\s*:\s*/.exec(
      text
    );
  if (!match) return text.trim();
  return text.slice(0, match.index).trim();
}

/**
 * Detects a structured card payload in an agent message.
 * Returns the matched key, the parsed JSON, and any human-readable prefix text.
 */
export function parseCardPayload(content: string): ParsedCard | null {
  for (const key of CARD_KEYS) {
    const idx = content.indexOf(key);
    if (idx === -1) continue;
    const afterKey = content.slice(idx + key.length);
    const jsonPart = extractJson(afterKey);
    if (!jsonPart) continue;
    try {
      const json = JSON.parse(unescapeUnicode(jsonPart));
      // Strip a leading "📦 " that often precedes the key.
      const prefix = content
        .slice(0, idx)
        .trim()
        .replace(/\s*📦\s*$/, "");
      return { key, json, prefix };
    } catch {
      continue;
    }
  }
  return null;
}

export function cardLabel(key: string): string {
  const map: Record<string, string> = {
    "single_record:": "Record",
    "retrieved_records:": "Records",
    "quote_details:": "Quote",
    "update_details:": "Quote",
    "intelligence_dashboard:": "Insights",
    "validation_rules_details:": "Validation Rules",
    "inclusion_rules_details:": "Inclusion Rules",
    "exclusion_rules_details": "Exclusion Rules",
    "action_triggers_details:": "Action Triggers",
    "email_alerts_details:": "Email Alerts",
    "rules:": "Rules",
    openGraphicBuilder: "Builder",
  };
  return map[key] || "Details";
}
