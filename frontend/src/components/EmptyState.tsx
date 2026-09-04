interface EmptyStateProps {
  userName: string;
  onExample: (text: string) => void;
}

const SUGGESTIONS = [
  { label: "Create a new quote", example: "Create a quote for Acme Labs." },
  { label: "New lead", example: "Create a new lead for Acme Corp." },
  { label: "Search records", example: "show account Acme Labs" },
  { label: "List Records", example: "Show my last 5 opportunities." },
  { label: "Insights", example: "Show my forecast grouped by month" },
];

export default function EmptyState({ userName, onExample }: EmptyStateProps) {
  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-6">
      <div className="w-full max-w-xl text-center">
        <div className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-primary">
          AgentCPQ Assistant
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          What can I do for you, <span className="text-primary">{userName}</span>?
        </h1>
        <p className="mt-2 text-[14px] text-muted-foreground">
          Ask me to create quotes, leads, opportunities, or search records.
        </p>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s.label}
              type="button"
              onClick={() => onExample(s.example)}
              className="rounded-full border border-border bg-white px-3.5 py-1.5 text-[13px] font-medium text-foreground/80 transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground"
            >
              {s.label}
            </button>
          ))}
        </div>

        <p className="mt-8 text-[13px] text-muted-foreground">
          Try: "Create a quote for Investors App with 5 seats."
        </p>
      </div>
    </div>
  );
}
