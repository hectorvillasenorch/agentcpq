import { useEffect, useState } from "react";
import { MessageSquare, PanelLeftClose, PanelLeftOpen, Pencil, Plus, Settings, Trash2 } from "lucide-react";
import type { ChatSession } from "../lib/types";

interface SidebarProps {
  sessions: ChatSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  isAdmin?: boolean;
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Sidebar({ sessions, activeId, onSelect, onNew, onDelete, onRename, isAdmin }: SidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem("agentcpq.sidebarCollapsed") === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem("agentcpq.sidebarCollapsed", collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  const startEdit = (s: ChatSession) => {
    setEditingId(s.session_id);
    setEditValue(s.title || "");
  };

  const commitEdit = (id: string) => {
    const title = editValue.trim();
    if (title) onRename(id, title);
    setEditingId(null);
  };

  if (collapsed) {
    return (
      <aside className="flex h-full w-14 shrink-0 flex-col items-center gap-2 border-r border-border bg-background py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <img src="/static/img/agentcpq-chat-icon-white.png" alt="AgentCPQ" className="h-5 w-5 object-contain" />
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          aria-label="Expand sidebar"
          title="Expand sidebar"
          className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <PanelLeftOpen size={16} />
        </button>
        <button
          type="button"
          onClick={onNew}
          aria-label="New chat"
          title="New chat"
          className="mt-1 rounded-lg border border-border bg-white p-2 text-foreground transition-colors hover:bg-muted"
        >
          <Plus size={15} />
        </button>
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          aria-label="Show conversations"
          title={`${sessions.length} conversation(s)`}
          className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <MessageSquare size={16} />
        </button>
        <div className="mt-auto flex flex-col items-center gap-2">
          {isAdmin && (
            <a
              href="/cpq/admin/custom-fields/"
              aria-label="Admin"
              title="Admin"
              className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Settings size={16} />
            </a>
          )}
          <a
            href="/logout/"
            aria-label="Sign out"
            title="Sign out"
            className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <span className="block h-5 w-5 rounded-full bg-muted" />
          </a>
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-border bg-background">
      <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <img src="/static/img/agentcpq-chat-icon-white.png" alt="AgentCPQ" className="h-5 w-5 object-contain" />
        </div>
        <div className="text-[15px] font-semibold tracking-tight">AgentCPQ</div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          aria-label="Collapse sidebar"
          title="Collapse sidebar"
          className="ml-auto rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <PanelLeftClose size={16} />
        </button>
      </div>

      <div className="px-3 pb-3">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-white px-3 py-2 text-[13px] font-medium text-foreground transition-colors hover:bg-muted"
        >
          <Plus size={15} />
          New chat
        </button>
      </div>

      <div className="px-5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Conversations
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {sessions.length === 0 && (
          <p className="px-3 py-2 text-[13px] text-muted-foreground">No conversations yet.</p>
        )}
        {sessions.map((s) => {
          const active = s.session_id === activeId;
          const editing = editingId === s.session_id;
          return (
            <div
              key={s.session_id}
              className={`group mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-colors ${
                active ? "bg-accent/10 text-foreground" : "text-foreground/80 hover:bg-muted"
              }`}
            >
              {editing ? (
                <input
                  autoFocus
                  type="text"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitEdit(s.session_id);
                    else if (e.key === "Escape") setEditingId(null);
                  }}
                  onBlur={() => commitEdit(s.session_id)}
                  className="min-w-0 flex-1 rounded-md border border-[#E2E8F0] bg-white px-2 py-1 text-[13px] text-foreground outline-none focus:border-[#3B62D9]"
                />
              ) : (
                <button
                  type="button"
                  onClick={() => onSelect(s.session_id)}
                  className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                >
                  <MessageSquare size={14} className="shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">
                      {s.title || "Untitled"}
                    </span>
                    <span className="block text-[11px] text-muted-foreground">
                      {formatRelative(s.created_at)}
                    </span>
                  </span>
                </button>
              )}
              {!editing && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    startEdit(s);
                  }}
                  aria-label="Rename conversation"
                  title="Rename"
                  className="shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted group-hover:opacity-100"
                >
                  <Pencil size={13} />
                </button>
              )}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.session_id);
                }}
                aria-label="Delete conversation"
                title="Delete"
                className="shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </nav>

      <div className="border-t border-border p-3">
        {isAdmin && (
          <a
            href="/cpq/admin/custom-fields/"
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Settings size={14} className="shrink-0" />
            Admin
          </a>
        )}
        <a
          href="/logout/"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <span className="h-6 w-6 rounded-full bg-muted" />
          Sign out
        </a>
      </div>
    </aside>
  );
}
