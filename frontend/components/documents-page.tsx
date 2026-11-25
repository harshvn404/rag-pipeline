"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, FolderOpen, RefreshCw } from "lucide-react";
import { useSession } from "@/components/session-context";
import { listDocuments, type DocumentRecord } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";

function statusClass(status: string): string {
  if (status === "completed") return "bg-panel text-positive";
  if (status === "failed") return "bg-panel text-negative";
  return "bg-panel text-secondary";
}

export default function DocumentsPage() {
  const { token } = useSession();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;

    listDocuments(token)
      .then((data) => {
        if (!active) return;
        setDocuments(data);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "Unable to load documents");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [token, reloadKey]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-secondary">Library</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.03em]">Documents</h1>
          <p className="mt-3 max-w-xl text-[15px] leading-7 text-secondary">
            Every PDF you have uploaded, with its indexing status and retrieval counts.
          </p>
        </div>
        <button
          type="button"
          className="button"
          onClick={() => setReloadKey((current) => current + 1)}
        >
          <RefreshCw aria-hidden="true" className="size-4" strokeWidth={1.75} />
          Refresh
        </button>
      </header>

      {error ? (
        <p className="mb-5 flex items-start gap-2 text-sm text-negative" role="alert">
          <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="panel px-5 py-12 text-center text-sm text-muted">Loading documents…</div>
      ) : documents.length === 0 ? (
        <div className="panel grid place-items-center px-6 py-20 text-center">
          <div className="grid max-w-sm gap-3">
            <span className="mx-auto flex size-10 items-center justify-center rounded-lg border border-line bg-raised">
              <FolderOpen aria-hidden="true" className="size-4 text-accent" strokeWidth={1.75} />
            </span>
            <p className="text-sm font-medium">No documents yet</p>
            <p className="text-sm leading-6 text-muted">
              Start a chat and attach a PDF to add it to your library.
            </p>
            <Link href="/" className="button button-primary mx-auto">
              Start a chat
            </Link>
          </div>
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="border-b border-line bg-raised">
                <tr>
                  <th scope="col" className="px-5 py-3 font-medium text-secondary">
                    Document
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium text-secondary">
                    Status
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium text-secondary">
                    Pages
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium text-secondary">
                    Chunks
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium text-secondary">
                    Added
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {documents.map((document) => (
                  <tr key={document.id}>
                    <td className="px-5 py-4">
                      <p className="font-medium break-all">{document.filename}</p>
                      <p className="tabular mt-1 text-xs text-muted">{formatBytes(document.size)}</p>
                      {document.error ? (
                        <p className="mt-1 text-xs text-negative">{document.error}</p>
                      ) : null}
                    </td>
                    <td className="px-5 py-4">
                      <span
                        className={`rounded-md border border-line px-2 py-1 text-xs ${statusClass(document.status)}`}
                      >
                        {document.status}
                      </span>
                    </td>
                    <td className="tabular px-5 py-4 text-secondary">{document.pages ?? "—"}</td>
                    <td className="tabular px-5 py-4 text-secondary">{document.chunks ?? "—"}</td>
                    <td className="px-5 py-4 text-xs text-secondary">
                      {formatDateTime(document.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
