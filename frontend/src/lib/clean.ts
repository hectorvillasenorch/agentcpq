import DOMPurify from "dompurify";

/**
 * Matches the backend's `_decode_chat_text`: unescapes \uXXXX sequences
 * (the LLM sometimes double-escapes HTML as \u003C etc.).
 */
export function decodeUnicode(str: string): string {
  if (!str || !/\\u[\dA-F]{4}/i.test(str)) return str;
  try {
    return str.replace(/\\u[\dA-F]{4}/gi, (match) =>
      String.fromCharCode(parseInt(match.slice(2), 16))
    );
  } catch {
    return str;
  }
}

/**
 * Matches the backend's `_strip_session_summary_text`: drop accidental
 * session_summary artifact lines from agent messages.
 */
export function stripSessionSummaryLines(text: string): string {
  return text
    .split(/\r?\n/)
    .filter((line) => !/session_summary/i.test(line))
    .join("\n");
}

function iconSpan(icon: string, color: string): string {
  return `<span class="material-icons" style="font-size:18px;vertical-align:middle;color:${color};margin-right:6px;">${icon}</span>`;
}

/** Map raw emojis to clean Material icons (AI-first, no emoji). */
const EMOJI_ICONS: Array<{ pattern: RegExp; icon: string; color: string }> = [
  { pattern: /📊/g, icon: "view_list", color: "#3B62D9" },
  { pattern: /📈/g, icon: "trending_up", color: "#3B62D9" },
  { pattern: /📉/g, icon: "trending_down", color: "#3B62D9" },
  { pattern: /📋/g, icon: "list_alt", color: "#3B62D9" },
  { pattern: /📄/g, icon: "description", color: "#3B62D9" },
  { pattern: /📦/g, icon: "inventory_2", color: "#3B62D9" },
  { pattern: /✅|✔️|✔/g, icon: "check_circle", color: "#00c000" },
  { pattern: /⚠️?/g, icon: "warning", color: "#eab308" },
  { pattern: /🛑/g, icon: "error", color: "#ef4444" },
  { pattern: /❌/g, icon: "cancel", color: "#ef4444" },
  { pattern: /❓|❔|🤔/g, icon: "help", color: "#3B62D9" },
  { pattern: /🔄/g, icon: "refresh", color: "#3B62D9" },
  { pattern: /🎉/g, icon: "celebration", color: "#00c000" },
  { pattern: /📝/g, icon: "edit_note", color: "#3B62D9" },
  { pattern: /💡/g, icon: "lightbulb", color: "#eab308" },
  { pattern: /🔍/g, icon: "search", color: "#3B62D9" },
];

export function replaceEmojisWithIcons(text: string): string {
  let out = text;
  for (const { pattern, icon, color } of EMOJI_ICONS) {
    out = out.replace(pattern, iconSpan(icon, color));
  }
  return out;
}

/**
 * Clean agent message text so it can be rendered as safe HTML:
 *  1. unescape \uXXXX
 *  2. drop session_summary artifacts
 *  3. replace emojis with clean Material icons
 *  4. convert newlines to <br> (same as backend `_decode_message_content`)
 *  5. sanitize the HTML (allows b/br/ul/li/span/icons/links, strips scripts)
 */
export function cleanAgentHtml(raw: string): string {
  if (!raw) return "";
  const decoded = decodeUnicode(raw);
  const stripped = stripSessionSummaryLines(decoded);
  const iconified = replaceEmojisWithIcons(stripped);
  const withBreaks = iconified.replace(/\r\n/g, "\n").replace(/\n/g, "<br>");
  return DOMPurify.sanitize(withBreaks);
}
