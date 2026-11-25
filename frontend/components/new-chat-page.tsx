"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, FileText } from "lucide-react";
import PdfIntake from "@/components/pdf-intake";
import { useSession } from "@/components/session-context";
import { createChat, uploadPdf } from "@/lib/api";

export default function NewChatPage() {
  const router = useRouter();
  const { token } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(files: File[]) {
    setBusy(true);
    setError(null);

    try {
      const documentIds: string[] = [];
      for (const file of files) {
        const upload = await uploadPdf(token, file);
        documentIds.push(upload.document_id);
      }

      const chat = await createChat(token, { document_ids: documentIds });
      router.push(`/chat/${chat.id}`);
      router.refresh();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to create the chat";
      setError(message);
      throw cause;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col items-center justify-center px-6 py-16 text-center">
      <span className="flex size-11 items-center justify-center rounded-xl border border-line bg-panel">
        <FileText aria-hidden="true" className="size-5 text-accent" strokeWidth={1.75} />
      </span>
      <p className="mt-6 text-sm text-secondary">Step 1 · Add sources</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-[-0.035em]">Start with a PDF</h1>
      <p className="mt-4 max-w-lg text-[15px] leading-7 text-secondary">
        Select one or more PDFs to create a chat. After indexing finishes, you can ask questions in
        that same chat.
      </p>

      <div className="mt-10 w-full">
        <PdfIntake onFiles={handleFiles} busy={busy} />
      </div>

      {error ? (
        <p className="mt-6 flex items-start gap-2 text-sm text-negative" role="alert">
          <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
          {error}
        </p>
      ) : null}
    </div>
  );
}
