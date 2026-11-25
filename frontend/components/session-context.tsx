"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { AuthUser } from "@/lib/api";

export type Session = {
  token: string;
  user: AuthUser;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({
  value,
  children,
}: {
  value: Session;
  children: ReactNode;
}) {
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Session provider is missing");
  return session;
}
