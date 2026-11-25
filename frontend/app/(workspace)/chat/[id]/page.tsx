import { Suspense } from "react";
import ChatConversation from "@/components/chat-page";

export const instant = false;

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<div className="grid h-full place-items-center text-sm text-muted">Opening chat…</div>}>
      <ChatConversation params={params} />
    </Suspense>
  );
}
