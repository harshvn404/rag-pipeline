import type { AuthResponse, AuthUser } from "./api";

const TOKEN_KEY = "marginal.token";
const USER_KEY = "marginal.user";

export type StoredAuth = {
  token: string;
  user: AuthUser;
};

const listeners = new Set<() => void>();
let snapshot: StoredAuth | null | undefined;

function readAuth(): StoredAuth | null {
  if (typeof window === "undefined") return null;

  try {
    const token = window.localStorage.getItem(TOKEN_KEY);
    const rawUser = window.localStorage.getItem(USER_KEY);
    if (!token || !rawUser) return null;

    const user = JSON.parse(rawUser) as AuthUser;
    if (typeof user.id !== "string" || typeof user.username !== "string") {
      return null;
    }

    return { token, user };
  } catch {
    return null;
  }
}

function emit(): void {
  for (const listener of listeners) listener();
}

export function getAuthSnapshot(): StoredAuth | null {
  if (typeof window === "undefined") return null;
  if (snapshot === undefined) snapshot = readAuth();
  return snapshot;
}

export function getServerAuthSnapshot(): null {
  return null;
}

export function subscribeAuth(listener: () => void): () => void {
  listeners.add(listener);

  const handleStorage = (event: StorageEvent) => {
    if (event.key === TOKEN_KEY || event.key === USER_KEY || event.key === null) {
      snapshot = readAuth();
      emit();
    }
  };

  window.addEventListener("storage", handleStorage);

  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", handleStorage);
  };
}

export function storeAuth(auth: AuthResponse): StoredAuth {
  const stored = { token: auth.access_token, user: auth.user };
  window.localStorage.setItem(TOKEN_KEY, stored.token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(stored.user));
  snapshot = stored;
  emit();
  return stored;
}

export function clearAuth(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  snapshot = null;
  emit();
}
