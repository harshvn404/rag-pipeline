"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FileText, FolderOpen, Home, LogOut, MessageSquare, Plus } from "lucide-react";
import { useSession } from "@/components/session-context";
import { listChats, type ChatSummary } from "@/lib/api";
import { apiHost } from "@/lib/client-config";

function navClass(active: boolean): string {
  return `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
    active ? "bg-panel text-ink" : "text-secondary hover:bg-panel hover:text-ink"
  }`;
}

export default function AppShell({
  children,
  onSignOut,
}: {
  children: ReactNode;
  onSignOut: () => void;
}) {
  const { token, user } = useSession();
  const pathname = usePathname();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    listChats(token)
      .then((data) => {
        if (!active) return;
        setChats(data);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "Unable to load chats");
      });

    return () => {
      active = false;
    };
  }, [token, pathname]);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[264px_minmax(0,1fr)]">
      <aside className="hidden flex-col border-r border-line bg-raised p-5 lg:flex">
        <Link href="/" className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-lg border border-line bg-panel">
            <FileText aria-hidden="true" className="size-4 text-accent" strokeWidth={1.75} />
          </span>
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Marginal</span>
        </Link>

        <Link href="/" className="button button-primary mt-7">
          <Plus aria-hidden="true" className="size-4" strokeWidth={1.75} />
          New chat
        </Link>

        <nav className="mt-6 grid gap-1" aria-label="Main navigation">
          <Link href="/" className={navClass(pathname === "/")}>
            <Home aria-hidden="true" className="size-4" strokeWidth={1.75} />
            Home
          </Link>
          <Link href="/documents" className={navClass(pathname === "/documents")}>
            <FolderOpen aria-hidden="true" className="size-4" strokeWidth={1.75} />
            Documents
          </Link>
        </nav>

        <section className="mt-8 min-h-0 flex-1 border-t border-line pt-5">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-medium text-muted">Chats</h2>
            <span className="tabular text-xs text-muted">{chats.length}</span>
          </div>

          {error ? (
            <p className="mt-3 text-xs leading-5 text-negative">{error}</p>
          ) : chats.length === 0 ? (
            <p className="mt-3 text-xs leading-5 text-muted">No chats yet.</p>
          ) : (
            <nav className="mt-3 grid gap-1" aria-label="Chat history">
              {chats.map((chat) => (
                <Link
                  key={chat.id}
                  href={`/chat/${chat.id}`}
                  className={navClass(pathname === `/chat/${chat.id}`)}
                  title={chat.title}
                >
                  <MessageSquare aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
                  <span className="truncate">{chat.title}</span>
                </Link>
              ))}
            </nav>
          )}
        </section>

        <div className="border-t border-line pt-5">
          <p className="truncate text-sm font-medium">{user.username}</p>
          <p className="tabular mt-1 text-xs text-muted">{apiHost()}</p>
          <button type="button" className="button button-quiet mt-3 w-full justify-start" onClick={onSignOut}>
            <LogOut aria-hidden="true" className="size-4" strokeWidth={1.75} />
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="flex h-14 items-center justify-between gap-4 border-b border-line px-4 lg:hidden">
          <Link href="/" className="flex items-center gap-2 text-sm font-medium">
            <span className="flex size-8 items-center justify-center rounded-lg border border-line bg-panel">
              <FileText aria-hidden="true" className="size-4 text-accent" strokeWidth={1.75} />
            </span>
            Marginal
          </Link>
          <div className="flex items-center gap-2">
            <Link href="/documents" className="button">
              <FolderOpen aria-hidden="true" className="size-4" strokeWidth={1.75} />
              Documents
            </Link>
            <button type="button" className="button button-quiet" onClick={onSignOut}>
              <LogOut aria-hidden="true" className="size-4" strokeWidth={1.75} />
              Sign out
            </button>
          </div>
        </header>

        <main id="main" className="min-h-[calc(100vh-3.5rem)] lg:min-h-screen">
          {children}
        </main>
      </div>
    </div>
  );
}
