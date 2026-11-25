"use client";

import { useSyncExternalStore } from "react";
import AppShell from "@/components/app-shell";
import AuthScreen from "@/components/auth-screen";
import { SessionProvider } from "@/components/session-context";
import {
  clearAuth,
  getAuthSnapshot,
  getServerAuthSnapshot,
  storeAuth,
  subscribeAuth,
} from "@/lib/auth";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getServerAuthSnapshot);

  if (!auth) {
    return (
      <AuthScreen
        onAuthenticated={(value) => {
          storeAuth(value);
        }}
      />
    );
  }

  return (
    <SessionProvider value={{ token: auth.token, user: auth.user }}>
      <AppShell
        onSignOut={() => {
          clearAuth();
        }}
      >
        {children}
      </AppShell>
    </SessionProvider>
  );
}
