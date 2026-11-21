// Thin client for the Django API. Authentication is a session cookie, so every
// write must also send Django's CSRF token back in a header.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public body?: any
  ) {
    super(message);
  }
}

export interface User {
  id: number;
  username: string;
}

export type DocStatus = "queued" | "processing" | "ready" | "failed";

export interface Doc {
  id: number;
  name: string;
  size: number;
  status: DocStatus;
  error: string;
  pages: number | null;
  chunk_count: number;
  uploaded_at: string;
}

export interface Source {
  document_id: number | null;
  document: string;
  page: number | null;
  snippet: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  created_at: string;
}

export interface ConversationSummary {
  id: number;
  title: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[];
}

function cookie(name: string): string {
  const match = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

let csrfReady = false;
async function ensureCsrf() {
  if (csrfReady && cookie("csrftoken")) return;
  await fetch("/api/auth/csrf/", { credentials: "same-origin" });
  csrfReady = true;
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    await ensureCsrf();
    headers["X-CSRFToken"] = cookie("csrftoken");
  }
  let payload: BodyInit | undefined;
  if (form) {
    payload = form; // the browser sets the multipart boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload, credentials: "same-origin" });
  if (res.status === 204) return undefined as T;
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const detail =
      (data && (data.detail || data.error)) ||
      (res.status === 429 ? "Too many requests. Please wait a moment." : `Request failed (${res.status}).`);
    throw new ApiError(res.status, String(detail), data?.code, data);
  }
  return data as T;
}

export const api = {
  me: () => request<User>("GET", "/api/auth/me/"),
  login: (username: string, password: string) => request<User>("POST", "/api/auth/login/", { username, password }),
  register: (username: string, password: string) =>
    request<User>("POST", "/api/auth/register/", { username, password }),
  logout: () => request<void>("POST", "/api/auth/logout/", {}),

  documents: () => request<Doc[]>("GET", "/api/documents/"),
  upload: (file: File, replace = false) => {
    const form = new FormData();
    form.append("file", file);
    if (replace) form.append("replace", "true");
    return request<Doc>("POST", "/api/documents/", undefined, form);
  },
  deleteDocument: (id: number) => request<void>("DELETE", `/api/documents/${id}/`),

  conversations: () => request<ConversationSummary[]>("GET", "/api/conversations/"),
  conversation: (id: number) => request<ConversationDetail>("GET", `/api/conversations/${id}/`),
  deleteConversation: (id: number) => request<void>("DELETE", `/api/conversations/${id}/`),
  ask: (question: string, conversation?: number) =>
    request<{ conversation: ConversationSummary; messages: Message[] }>("POST", "/api/chat/", {
      question,
      conversation,
    }),
};
