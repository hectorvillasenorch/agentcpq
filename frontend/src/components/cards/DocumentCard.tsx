import { Download, FileText } from "lucide-react";

interface DocumentPayload {
  download_url?: string;
  document_version?: unknown;
  [key: string]: unknown;
}

/** A generated document (e.g. quote PDF) with a download button. */
export default function DocumentCard({ payload }: { payload: DocumentPayload }) {
  const url = typeof payload.download_url === "string" ? payload.download_url : "";
  const version = payload.document_version ?? "";

  return (
    <div className="flex items-center gap-3 rounded-lg border border-[#EDEEF1] bg-white px-4 py-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#EEF2FF] text-[#3B62D9]">
        <FileText size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-foreground">PDF generated</div>
        <div className="text-[11px] text-muted-foreground">Version v{String(version)}</div>
      </div>
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          <Download size={14} />
          Download
        </a>
      ) : (
        <span className="text-[12px] text-muted-foreground">No file</span>
      )}
    </div>
  );
}
