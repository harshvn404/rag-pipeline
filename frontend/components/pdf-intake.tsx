"use client";

import { useRef, useState } from "react";
import { AlertCircle, FileUp } from "lucide-react";
import { selectPdfFiles } from "@/lib/pdf";

export default function PdfIntake({
  onFiles,
  busy = false,
}: {
  onFiles: (files: File[]) => Promise<void>;
  busy?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(incoming: FileList | File[] | null) {
    const { pdfs, hasInvalid } = selectPdfFiles(incoming);
    if (hasInvalid) {
      setError("Only PDF files can be uploaded.");
    } else {
      setError(null);
    }
    if (pdfs.length === 0) return;

    try {
      await onFiles(pdfs);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to upload PDFs");
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div
        className={`panel grid gap-4 p-6 transition-colors ${dragging ? "border-accent" : ""}`}
        aria-busy={busy}
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
      >
        <input
          ref={inputRef}
          id="new-chat-pdfs"
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          aria-label="Select PDF files"
          disabled={busy}
          onChange={(event) => {
            void handleFiles(event.target.files);
            event.target.value = "";
          }}
        />

        <span className="flex size-11 items-center justify-center rounded-xl border border-line bg-raised">
          <FileUp aria-hidden="true" className="size-5 text-accent" strokeWidth={1.75} />
        </span>

        <div className="grid gap-2 text-left">
          <p className="text-[15px] font-medium">
            {busy ? "Uploading and preparing your PDFs…" : "Select one or more PDFs"}
          </p>
          <p className="text-sm leading-6 text-secondary">
            Upload starts immediately. Questions become available in the chat once indexing finishes.
          </p>
        </div>

        <button
          type="button"
          className="button button-primary justify-self-start"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "Uploading…" : "Choose PDFs"}
          <FileUp aria-hidden="true" className="size-4" strokeWidth={1.75} />
        </button>
      </div>

      <div aria-live="polite" aria-atomic="true" className="min-h-5 px-1 pt-2 text-sm">
        {error ? (
          <span className="flex items-start gap-2 text-negative">
            <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
            {error}
          </span>
        ) : null}
      </div>
    </div>
  );
}
