// Shared by the real API client and the in-browser demo backend.

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
