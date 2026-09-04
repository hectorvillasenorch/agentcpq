import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, ChatSession } from "./lib/types";
import { fetchMessages, fetchSessions, sendChatStream, deleteSession, renameSession } from "./lib/api";
import { parseCardPayload } from "./lib/messageParser";
import Sidebar from "./components/Sidebar";
import EmptyState from "./components/EmptyState";
import ChatInput from "./components/ChatInput";
import MessageBubble from "./components/MessageBubble";
import { Spinner } from "./components/ui";

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focusSignal, setFocusSignal] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  const userName =
    document.body.dataset.userName || "there";
  const isAdmin = document.body.dataset.isAdmin === "true";

  const refreshSessions = useCallback(async () => {
    try {
      const list = await fetchSessions();
      setSessions(list);
    } catch {
      /* non-fatal */
    }
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    activeIdRef.current = sessionId;
    setActiveId(sessionId);
    setLoading(true);
    setError(null);
    try {
      const msgs = await fetchMessages(sessionId);
      // Structured-card agent messages are stored with hiddenMessage=True by the
      // backend, but they must still render on refresh.
      setMessages(
        msgs.filter(
          (m) => !m.hidden || (m.sender === "agent" && parseCardPayload(m.content) !== null)
        )
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load messages.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Keep the ref in sync so async send handlers always read the current session.
    activeIdRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session_id");
    // Always load the sidebar sessions, even when deep-linking to a session.
    refreshSessions();
    if (sid) {
      loadSession(sid);
    }
  }, [loadSession, refreshSessions]);

  // Keep the URL in sync so refresh/deep-links keep the session.
  useEffect(() => {
    if (activeId) {
      window.history.replaceState(
        null,
        "",
        `/agents/spa/?session_id=${encodeURIComponent(activeId)}`
      );
    }
  }, [activeId]);

  const startNewChat = useCallback(() => {
    activeIdRef.current = null;
    setActiveId(null);
    setMessages([]);
    setError(null);
    setFocusSignal((n) => n + 1);
  }, []);

  const handleDelete = useCallback(
    async (sessionId: string) => {
      try {
        await deleteSession(sessionId);
      } catch {
        /* non-fatal */
      }
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (activeId === sessionId) {
        setActiveId(null);
        setMessages([]);
      }
    },
    [activeId]
  );

  const handleRename = useCallback(
    async (sessionId: string, title: string) => {
      try {
        await renameSession(sessionId, title);
        setSessions((prev) =>
          prev.map((s) => (s.session_id === sessionId ? { ...s, title } : s))
        );
      } catch {
        /* non-fatal */
      }
    },
    []
  );

  const handleSend = useCallback(
    async (text: string) => {
      setError(null);
      setSending(true);
      const now = new Date().toISOString();
      const userMsg: ChatMessage = { sender: "user", content: text, timestamp: now, hidden: false };
      const streamId = `stream-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const placeholder: ChatMessage = {
        sender: "agent",
        content: "",
        timestamp: now,
        hidden: false,
        streamId,
      };
      setMessages((prev) => [...prev, userMsg, placeholder]);

      const patch = (updater: (m: ChatMessage) => ChatMessage) => {
        setMessages((prev) => prev.map((m) => (m.streamId === streamId ? updater(m) : m)));
      };

      try {
        const { sessionId } = await sendChatStream(text, activeIdRef.current ?? undefined, {
          onToken: (delta) => patch((m) => ({ ...m, content: m.content + delta })),
          // Rows arrive before the final message; render the table only once the
          // message text is ready so the table never appears above/before the message.
          onRows: () => {},
          onDone: (final) => {
            patch((m) => ({ ...m, content: final.text, cards: final.cards, streamId: undefined }));
            if (final.sessionId) {
              activeIdRef.current = final.sessionId;
              setActiveId(final.sessionId);
            }
          },
          onError: (msg) => setError(msg),
        });
        if (sessionId) {
          activeIdRef.current = sessionId;
          setActiveId(sessionId);
        }
        await refreshSessions();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Something went wrong.");
      } finally {
        setSending(false);
        // Refocus the input so the user can type immediately after the reply.
        setFocusSignal((n) => n + 1);
      }
    },
    [refreshSessions]
  );

  useEffect(() => {
    // Instant scroll while streaming (avoids stacking smooth-scroll animations),
    // smooth otherwise.
    bottomRef.current?.scrollIntoView({ behavior: sending ? "auto" : "smooth" });
  }, [messages, loading, sending]);

  return (
    <div className="flex h-full overflow-hidden bg-background text-foreground">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={loadSession}
        onNew={startNewChat}
        onDelete={handleDelete}
        onRename={handleRename}
        isAdmin={isAdmin}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {messages.length === 0 && !loading ? (
          <div className="flex-1">
            <EmptyState userName={userName} onExample={handleSend} />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <div className="flex w-full flex-col gap-5 px-6 py-6">
              {messages.map((m, i) => (
                <MessageBubble key={i} message={m} sessionId={activeId} isAdmin={isAdmin} onSendMessage={handleSend} />
              ))}
              {loading && (
                <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
                  <Spinner />
                  Loading…
                </div>
              )}
              {error && (
                <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] text-destructive">
                  {error}
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>
        )}

        <ChatInput onSend={handleSend} disabled={sending || loading} focusSignal={focusSignal} sessionId={activeId} />
      </main>
    </div>
  );
}
