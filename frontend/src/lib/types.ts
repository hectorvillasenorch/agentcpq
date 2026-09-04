export interface ChatSession {
  session_id: string;
  title: string;
  created_at: string;
}

export interface ChatMessage {
  sender: "user" | "agent";
  content: string;
  timestamp: string;
  hidden: boolean;
  /** Structured card payloads attached to a live agent response. */
  cards?: ParsedCard[];
  /** Temporary id used to update a message while it is being streamed. */
  streamId?: string;
}

export interface ChatResponse {
  response: string | Record<string, unknown>;
}

export interface ParsedCard {
  key: string;
  json: unknown;
  prefix: string;
}
