"use client";

import { useRef, useState } from "react";
import { AlertCircle, ArrowUp, Paperclip } from "lucide-react";
import { selectPdfFiles } from "@/lib/pdf";

export type ComposerSubmission = {
  content: string;
};

export default function ChatComposer({
  onSubmit,
  onFilesSelected,
  busy = false,
  uploading = false,
  messageDisabled = false,
  placeholder = "Ask a question…",
}: {
  onSubmit: (submission: ComposerSubmission) => Promise<void>;
  onFilesSelected: (files: File[]) => Promise<void>;
  busy?: boolean;
  uploading?: boolean;
  messageDisabled?: boolean;
  placeholder?: string;
}) {
  const [content, setContent] = useState("");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFiles(incoming: FileList | File[] | null) {
    if (busy || uploading) return;

    const { pdfs, hasInvalid } = selectPdfFiles(incoming);
    if (hasInvalid) {
      setError("Only PDF files can be uploaded.");
    } else {
      setError(null);
    }
    if (pdfs.length === 0) return;

    try {
      await onFilesSelected(pdfs);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to upload PDFs");
    }
  }

  async function submit() {
    const trimmed = content.trim();
    if (!trimmed) {
      setError("Type a message first.");
      return;
    }
    if (busy || messageDisabled) return;

    setError(null);
    try {
      await onSubmit({ content: trimmed });
      setContent("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to send message");
    }
  }

  return (
    <form
      className="mx-auto w-full max-w-3xl"
      aria-busy={busy || uploading}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void handleFiles(event.dataTransfer.files);
      }}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div
        className={`panel overflow-hidden transition-colors ${dragging ? "border-accent" : ""}`}
      >
        <textarea
          aria-label="Message"
          className="field min-h-24 resize-none rounded-none border-0 bg-transparent px-4 py-3 text-[15px] leading-6 focus:ring-0"
          value={content}
          placeholder={placeholder}
          onChange={(event) => setContent(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
          disabled={busy || messageDisabled}
          rows={2}
        />

        <div className="flex items-center justify-between gap-3 border-t border-line px-3 py-2">
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              id="chat-files"
              type="file"
              accept="application/pdf,.pdf"
              multiple
              className="sr-only"
              aria-label="Select PDF files"
              disabled={busy || uploading}
              onChange={(event) => {
                void handleFiles(event.target.files);
                event.target.value = "";
              }}
            />
            <button
              type="button"
              className="button button-quiet"
              aria-label="Upload PDF files"
              disabled={busy || uploading}
              onClick={() => fileInputRef.current?.click()}
            >
              <Paperclip aria-hidden="true" className="size-4" strokeWidth={1.75} />
              {uploading ? "Uploading…" : "Add PDFs"}
            </button>
            <span className="hidden text-xs text-muted sm:inline">
              Selecting a PDF uploads it immediately
            </span>
          </div>

          <button
            type="submit"
            className="button button-primary"
            disabled={busy || messageDisabled || !content.trim()}
          >
            {busy ? "Sending…" : "Send"}
            <ArrowUp aria-hidden="true" className="size-4" strokeWidth={1.75} />
          </button>
        </div>
      </div>

      <div aria-live="polite" aria-atomic="true" className="min-h-5 px-1 pt-2 text-sm">
        {error ? (
          <span className="flex items-start gap-2 text-negative">
            <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
            {error}
          </span>
        ) : null}
      </div>
    </form>
  );
}
