export type RetrievalMode = "hybrid" | "dense" | "bm25";

export type AuthUser = {
  id: string;
  username: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export type UploadResponse = {
  document_id: string;
  upload_id: string;
  filename: string;
  size: number;
  status: string;
};

export type DocumentRecord = UploadResponse & {
  id: string;
  pages: number | null;
  chunks: number | null;
  vectors_stored: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type SearchResult = {
  id: string;
  score: number;
  text: string | null;
  filename: string | null;
  page: number | null;
  chunk_index: number | null;
  upload_id: string | null;
  document_id: string | null;
};

export type SearchResponse = {
  query: string;
  top_k: number;
  mode: RetrievalMode;
  results: SearchResult[];
};

export type AskSource = {
  filename: string | null;
  page: number | null;
  chunk_index: number | null;
  score: number;
  upload_id: string | null;
  document_id: string | null;
};

export type AskResponse = {
  query: string;
  mode: RetrievalMode;
  top_k: number;
  answer: string;
  sources: AskSource[];
};

export type ChatMessage = {
  id: string;
  chat_id: string;
  role: "user" | "assistant";
  content: string;
  sources: AskSource[];
  created_at: string;
};

export type ChatDetail = ChatSummary & {
  documents: DocumentRecord[];
  messages: ChatMessage[];
};

export type CreateChatResponse = ChatSummary & {
  documents: DocumentRecord[];
};

export type ChatMessagePair = {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
};

type RequestOptions = {
  method?: "GET" | "POST";
  token?: string;
  body?: unknown;
  formData?: FormData;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function apiBaseUrl(): string {
  return API_BASE_URL;
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {}

  return `${response.status} ${response.statusText}`.trim();
}

async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers();

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body,
    });
  } catch {
    throw new Error(`Cannot reach the backend at ${API_BASE_URL}`);
  }

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return (await response.json()) as T;
}

export function register(username: string, password: string): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/auth/register", {
    method: "POST",
    body: { username, password },
  });
}

export function login(username: string, password: string): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

export function uploadPdf(token: string, file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<UploadResponse>("/upload-pdf", {
    method: "POST",
    token,
    formData,
  });
}

export function searchDocuments(
  token: string,
  payload: { query: string; top_k: number; mode: RetrievalMode },
): Promise<SearchResponse> {
  return apiFetch<SearchResponse>("/search", {
    method: "POST",
    token,
    body: payload,
  });
}

export function askQuestion(
  token: string,
  payload: { query: string; top_k: number; mode: RetrievalMode },
): Promise<AskResponse> {
  return apiFetch<AskResponse>("/ask", {
    method: "POST",
    token,
    body: payload,
  });
}

export function listDocuments(token: string): Promise<DocumentRecord[]> {
  return apiFetch<DocumentRecord[]>("/documents", { token });
}

export function listChats(token: string): Promise<ChatSummary[]> {
  return apiFetch<ChatSummary[]>("/chats", { token });
}

export function createChat(
  token: string,
  payload: { title?: string; document_ids: string[] },
): Promise<CreateChatResponse> {
  return apiFetch<CreateChatResponse>("/chats", {
    method: "POST",
    token,
    body: payload,
  });
}

export function addChatDocuments(
  token: string,
  chatId: string,
  documentIds: string[],
): Promise<CreateChatResponse> {
  return apiFetch<CreateChatResponse>(`/chats/${encodeURIComponent(chatId)}/documents`, {
    method: "POST",
    token,
    body: { document_ids: documentIds },
  });
}

export function getChat(token: string, chatId: string): Promise<ChatDetail> {
  return apiFetch<ChatDetail>(`/chats/${encodeURIComponent(chatId)}`, { token });
}

export function postChatMessage(
  token: string,
  chatId: string,
  payload: { content: string; top_k: number; mode: RetrievalMode },
): Promise<ChatMessagePair> {
  return apiFetch<ChatMessagePair>(`/chats/${encodeURIComponent(chatId)}/messages`, {
    method: "POST",
    token,
    body: payload,
  });
}
