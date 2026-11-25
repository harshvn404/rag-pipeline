"use client";

import { use, useEffect, useState } from "react";
import { AlertCircle, FileText, MessageSquare } from "lucide-react";
import ChatComposer, { type ComposerSubmission } from "@/components/chat-composer";
import { useSession } from "@/components/session-context";
import {
  addChatDocuments,
  getChat,
  postChatMessage,
  uploadPdf,
  type AskSource,
  type ChatDetail,
  type ChatMessage,
} from "@/lib/api";
import { formatDateTime, formatScore } from "@/lib/format";

export default function ChatConversation({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { token } = useSession();
  const [chat, setChat] = useState<ChatDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pollKey, setPollKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;

    async function refresh(): Promise<boolean> {
      try {
        const data = await getChat(token, id);
        if (!active) return true;
        setChat((current) => (current ? { ...current, documents: data.documents } : data));
        return !data.documents.some(
          (document) => document.status === "queued" || document.status === "processing",
        );
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Unable to load chat");
        }
        return true;
      } finally {
        if (active) setLoading(false);
      }
    }

    void refresh().then((done) => {
      if (!active || done) return;
      timer = setInterval(() => {
        void refresh().then((ready) => {
          if (ready && timer) {
            clearInterval(timer);
            timer = undefined;
          }
        });
      }, 1200);
    });

    return () => {
      active = false;
      if (timer) clearInterval(timer);
    };
  }, [token, id, pollKey]);

  async function handleFiles(files: File[]) {
    setUploading(true);
    setError(null);

    try {
      const documentIds: string[] = [];
      for (const file of files) {
        const upload = await uploadPdf(token, file);
        documentIds.push(upload.document_id);
      }

      const attachedChat = await addChatDocuments(token, id, documentIds);
      setChat((current) => (current ? { ...current, documents: attachedChat.documents } : current));
      setPollKey((current) => current + 1);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to upload PDFs";
      setError(message);
      throw cause;
    } finally {
      setUploading(false);
    }
  }

  async function handleSubmit({ content }: ComposerSubmission) {
    setBusy(true);
    setError(null);

    try {
      const pair = await postChatMessage(token, id, { content, top_k: 5, mode: "hybrid" });
      setChat((current) =>
        current
          ? {
              ...current,
              updated_at: pair.assistant_message.created_at,
              messages: [...current.messages, pair.user_message, pair.assistant_message],
            }
          : current,
      );
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to send message";
      setError(message);
      throw cause;
    } finally {
      setBusy(false);
    }
  }

  const indexing =
    chat?.documents.some(
      (document) => document.status === "queued" || document.status === "processing",
    ) ?? false;
  const hasReadyDocument = chat?.documents.some((document) => document.status === "completed") ?? false;
  const canSend = hasReadyDocument && !indexing;
  const documentCount = chat?.documents.length ?? 0;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line px-6 py-4">
        <div className="mx-auto max-w-3xl">
          <p className="text-xs text-muted">Chat</p>
          <h1 className="mt-1 truncate text-lg font-semibold tracking-[-0.01em]">
            {chat?.title ?? "Chat"}
          </h1>
          {documentCount > 0 ? (
            <p className="tabular mt-1 flex items-center gap-2 text-xs text-muted">
              <FileText aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
              {documentCount} PDF{documentCount === 1 ? "" : "s"} ·{" "}
              {indexing ? "indexing" : canSend ? "ready" : "no usable documents"}
            </p>
          ) : (
            <p className="mt-1 text-xs text-muted">No PDFs in this chat yet</p>
          )}
        </div>
      </header>

      <section className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
        {error ? (
          <p className="mb-6 flex items-start gap-2 text-sm text-negative" role="alert">
            <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
            {error}
          </p>
        ) : null}

        {loading ? (
          <p className="text-center text-sm text-muted">Loading messages…</p>
        ) : chat && chat.messages.length > 0 ? (
          <ol className="grid gap-7">
            {chat.messages.map((message) => (
              <MessageRow key={message.id} message={message} />
            ))}
          </ol>
        ) : (
          <div className="grid place-items-center py-20 text-center">
            <div className="grid max-w-sm gap-3">
              <span className="mx-auto flex size-10 items-center justify-center rounded-lg border border-line bg-raised">
                <MessageSquare aria-hidden="true" className="size-4 text-accent" strokeWidth={1.75} />
              </span>
              <p className="text-sm font-medium">
                {indexing ? "Indexing PDFs" : canSend ? "No messages yet" : "Add a PDF to start"}
              </p>
              <p className="text-sm leading-6 text-muted">
                {indexing
                  ? "Questions unlock as soon as the PDFs are indexed."
                  : canSend
                    ? "Ask a question below to continue this chat."
                    : "Select a PDF below; uploading starts immediately."}
              </p>
            </div>
          </div>
        )}
      </section>

      <div className="sticky bottom-0 border-t border-line bg-canvas px-4 py-4">
        <ChatComposer
          onSubmit={handleSubmit}
          onFilesSelected={handleFiles}
          busy={busy}
          uploading={uploading}
          messageDisabled={!canSend}
          placeholder={
            indexing
              ? "Indexing PDFs…"
              : canSend
                ? "Ask about your PDFs…"
                : "Add a PDF to start asking…"
          }
        />
      </div>
    </div>
  );
}

function MessageRow({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <li className={isUser ? "ml-auto max-w-[88%]" : ""}>
      <div className={`mb-2 flex items-center gap-2 text-xs text-muted ${isUser ? "justify-end" : ""}`}>
        <span className="font-medium text-secondary">{isUser ? "You" : "Marginal"}</span>
        <span className="tabular">{formatDateTime(message.created_at)}</span>
      </div>

      <div
        className={`rounded-xl border border-line p-4 text-[15px] leading-7 whitespace-pre-wrap ${
          isUser ? "bg-raised" : "bg-panel"
        }`}
      >
        {message.content}
      </div>

      {!isUser && message.sources.length > 0 ? <SourceList sources={message.sources} /> : null}
    </li>
  );
}

function SourceList({ sources }: { sources: AskSource[] }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-2" aria-label="Answer sources">
      {sources.map((source, index) => (
        <li
          key={`${source.document_id ?? "source"}-${index}`}
          className="tabular rounded-md border border-line bg-panel px-2 py-1 text-xs text-secondary"
          title={source.filename ?? "Unknown document"}
        >
          {String(index + 1).padStart(2, "0")} · page {source.page ?? "—"} ·{" "}
          {formatScore(source.score)}
        </li>
      ))}
    </ul>
  );
}
