import type { ChatMessage, ParsedCard } from "../lib/types";
import { parseCardPayload, stripStructuredTail } from "../lib/messageParser";
import { cleanAgentHtml } from "../lib/clean";
import SingleRecordCard from "./cards/SingleRecordCard";
import RecordsTable from "./cards/RecordsTable";
import QuoteCard from "./cards/QuoteCard";
import DocumentCard from "./cards/DocumentCard";
import RecordSummaryCard from "./cards/RecordSummaryCard";
import ActionTriggersCard from "./cards/ActionTriggersCard";

function renderCard(
  card: ParsedCard,
  sessionId?: string | null,
  isAdmin?: boolean,
  onSendMessage?: (text: string) => void
) {
  if (card.key === "single_record:") {
    return <SingleRecordCard payload={card.json as never} sessionId={sessionId} isAdmin={isAdmin} />;
  }
  if (card.key === "single_record_summary:") {
    return <RecordSummaryCard payload={card.json as never} sessionId={sessionId} />;
  }
  if (card.key === "quote_details:" || card.key === "update_details:") {
    return <QuoteCard payload={card.json as never} sessionId={sessionId} />;
  }
  if (card.key === "document:") {
    return <DocumentCard payload={card.json as never} />;
  }
  if (card.key === "action_triggers_details:") {
    return <ActionTriggersCard payload={card.json} />;
  }
  return <RecordsTable payload={card.json} sessionId={sessionId} onSendMessage={onSendMessage} />;
}

/** Renders agent text as sanitized HTML (inline icons, <br>, <b>, lists). */
function AgentText({ html }: { html: string }) {
  // eslint-disable-next-line react/no-danger
  return <div dangerouslySetInnerHTML={{ __html: cleanAgentHtml(html) }} />;
}

function AgentContent({
  content,
  cards,
  sessionId,
  isAdmin,
  onSendMessage,
}: {
  content: string;
  cards?: ParsedCard[];
  sessionId?: string | null;
  isAdmin?: boolean;
  onSendMessage?: (text: string) => void;
}) {
  // Live responses carry structured cards separately; history messages embed them in content.
  if (cards && cards.length > 0) {
    const parsed = parseCardPayload(content);
    // Strip any trailing "key: {json}" dump that the backend appended to the text.
    const text = parsed ? parsed.prefix : stripStructuredTail(content);
    return (
      <div className="space-y-4">
        {text && <AgentText html={text} />}
        {cards.map((card, i) => (
          <div key={i}>{renderCard(card, sessionId, isAdmin, onSendMessage)}</div>
        ))}
      </div>
    );
  }

  const card = parseCardPayload(content);
  if (!card) {
    return <AgentText html={content} />;
  }

  return (
    <div className="space-y-4">
      {card.prefix && <AgentText html={card.prefix} />}
      {renderCard(card, sessionId, isAdmin, onSendMessage)}
    </div>
  );
}

export default function MessageBubble({
  message,
  sessionId,
  isAdmin,
  onSendMessage,
}: {
  message: ChatMessage;
  sessionId?: string | null;
  isAdmin?: boolean;
  onSendMessage?: (text: string) => void;
}) {
  if (message.sender === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] rounded-xl bg-[#DCE4FA] px-4 py-2.5 text-[15px] leading-snug text-[#3B62D9]">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>
      </div>
    );
  }

  const streaming = !!message.streamId;
  const showTyping = streaming && !message.content && (!message.cards || message.cards.length === 0);

  return (
    <div className="flex w-full items-start gap-3">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
        <img
          src="/static/img/agentcpq-chat-icon-sm.png"
          alt="AgentCPQ"
          className="h-[20px] w-[20px] object-contain"
        />
      </div>
      <div className="w-full min-w-0 rounded-xl border border-border bg-white px-5 py-4 text-[15px] leading-relaxed text-foreground">
        {showTyping ? (
          <div className="flex items-center gap-1 py-1">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60" />
          </div>
        ) : (
          <AgentContent content={message.content} cards={message.cards} sessionId={sessionId} isAdmin={isAdmin} onSendMessage={onSendMessage} />
        )}
      </div>
    </div>
  );
}
