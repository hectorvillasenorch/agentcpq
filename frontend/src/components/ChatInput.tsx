import { useEffect, useRef, useState } from "react";
import { Mic, SendHorizonal, Paperclip, X } from "lucide-react";
import { useDictation } from "../lib/useDictation";

interface ChatInputProps {
  onSend: (text: string) => void;
  disabled: boolean;
  focusSignal?: number;
  sessionId?: string | null;
}

interface Attachment {
  name: string;
  status: "uploading" | "uploaded" | "error";
}

const ALLOWED = ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"];
const MAX_SIZE = 8 * 1024 * 1024; // 8 MB

export default function ChatInput({ onSend, disabled, focusSignal, sessionId }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const baseRef = useRef("");

  // Prepend dictated text to whatever was already in the box, separating cleanly.
  const joinBase = (text: string) => {
    const base = baseRef.current;
    if (!text) return base;
    const sep = base && !/\s$/.test(base) ? " " : "";
    return base + sep + text;
  };

  const dictation = useDictation({
    onUpdate: (text) => setValue(joinBase(text)),
    onFinalize: (text) => setValue(joinBase(text)),
  });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [value]);

  // Focus the input when requested (new chat / after agent response).
  useEffect(() => {
    if (focusSignal) ref.current?.focus();
  }, [focusSignal]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
    baseRef.current = "";
  };

  const pickFile = () => fileRef.current?.click();

  const toggleDictation = () => {
    if (!dictation.listening) baseRef.current = value;
    dictation.toggle();
  };

  const uploadFile = async (file: File) => {
    if (!ALLOWED.includes(file.type)) {
      setAttachment({ name: file.name, status: "error" });
      return;
    }
    if (file.size > MAX_SIZE) {
      setAttachment({ name: file.name, status: "error" });
      return;
    }
    setAttachment({ name: file.name, status: "uploading" });
    const formData = new FormData();
    formData.append("file", file);
    if (sessionId) formData.append("session_id", sessionId);
    try {
      const res = await fetch("/agents/upload-attachment/", {
        method: "POST",
        credentials: "same-origin",
        body: formData,
      });
      if (!res.ok) throw new Error("upload failed");
      setAttachment({ name: file.name, status: "uploaded" });
    } catch {
      setAttachment({ name: file.name, status: "error" });
    }
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) void uploadFile(file);
  };

  return (
    <div className="px-4 pb-3 pt-2">
      {dictation.error && (
        <div className="mx-auto mb-1.5 flex w-full items-center justify-center gap-1.5 text-[11.5px] text-red-600">
          <Mic size={12} />
          {dictation.error}
        </div>
      )}
      <div className="mx-auto flex w-full items-center gap-2 rounded-full border border-border bg-white py-1 pl-4 pr-1.5 transition-colors focus-within:border-ring">
        <button
          type="button"
          onClick={pickFile}
          aria-label="Attach a file"
          title="Attach a file (appended to the next PDF)"
          className="shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Paperclip size={15} />
        </button>
        {dictation.supported && (
          <button
            type="button"
            onClick={toggleDictation}
            aria-label={dictation.listening ? "Stop dictation" : "Dictate with your microphone"}
            title={dictation.listening ? "Stop dictation" : "Dictate — click the mic, speak, click again to stop"}
            className={`relative shrink-0 rounded-full p-1.5 transition-colors ${
              dictation.listening
                ? "bg-red-50 text-red-500"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            <Mic size={15} />
            {dictation.listening && (
              <span className="absolute -right-0.5 -top-0.5 flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-red-500" />
              </span>
            )}
          </button>
        )}
        <input
          ref={fileRef}
          type="file"
          accept={ALLOWED.join(",")}
          onChange={onFileChange}
          className="hidden"
        />
        {attachment && (
          <span
            className={`flex max-w-[160px] items-center gap-1 truncate rounded-full px-2 py-0.5 text-[11px] ${
              attachment.status === "error"
                ? "bg-red-50 text-red-600"
                : attachment.status === "uploading"
                  ? "bg-muted text-muted-foreground"
                  : "bg-emerald-50 text-emerald-700"
            }`}
          >
            <span className="truncate">{attachment.name}</span>
            <button
              type="button"
              onClick={() => setAttachment(null)}
              aria-label="Remove attachment"
              className="shrink-0"
            >
              <X size={11} />
            </button>
          </span>
        )}
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="Ask me to create a quote, lead, or record..."
          className="max-h-[120px] min-h-[22px] flex-1 resize-none bg-transparent py-1 text-[14px] leading-snug text-foreground outline-none placeholder:text-muted-foreground"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !value.trim()}
          aria-label="Send message"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SendHorizonal size={14} />
        </button>
      </div>
    </div>
  );
}
