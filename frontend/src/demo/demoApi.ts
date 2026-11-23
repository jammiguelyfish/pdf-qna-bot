// A backend that runs entirely in the browser, used by the static GitHub Pages
// build (VITE_DEMO=1). It keeps the behaviours the real app is about:
//   - uploads are hashed (SHA-256) and checked for duplicates and name clashes
//   - replacing a file removes the old one and its content from search
//   - questions only search the documents that are currently "ready"
// What it cannot do is read PDFs you upload or run a language model. So the three
// sample PDFs are pre-chunked (by the real ingestion code, see
// scripts/export_demo.py), answers to the suggested questions were recorded from
// the real pipeline, and any other question returns the best-matching passages.
import { ApiError, ConversationDetail, ConversationSummary, Doc, DocStatus, Message, Source, User } from "../apiTypes";
import data from "./data.json";

interface Chunk {
  page: number;
  text: string;
}
interface StoredDoc extends Doc {
  hash: string;
  chunks: Chunk[];
}

const NO_DOCUMENTS =
  "You don't have any processed documents yet. Upload a PDF on the Documents page and wait until it shows as ready, then ask again.";

export const demoQuestions: string[] = data.answers.map((a) => a.question);
export const sampleFiles: { name: string; url: string }[] = data.docs.map((d) => ({
  name: d.name,
  url: `${import.meta.env.BASE_URL}samples/${d.name}`,
}));

const user: User = { id: 1, username: "demo" };
let nextId = 100;
let nextMessageId = 1;
const now = () => new Date().toISOString();
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

const docs: StoredDoc[] = data.docs.map((d, i) => ({
  id: i + 1,
  name: d.name,
  size: d.size,
  status: "ready" as DocStatus,
  error: "",
  pages: d.pages,
  chunk_count: d.chunks.length,
  uploaded_at: now(),
  hash: d.hash,
  chunks: d.chunks,
}));

// A replaced file keeps its name but not its content.
const originalHash = new Map(data.docs.map((d) => [d.name, d.hash]));
const isOriginal = (d: StoredDoc) => originalHash.get(d.name) === d.hash;

const conversations = new Map<number, { summary: ConversationSummary; messages: Message[] }>();

function publicDoc(d: StoredDoc): Doc {
  const { hash: _h, chunks: _c, ...rest } = d;
  return { ...rest };
}

const readBuffer = (blob: Blob): Promise<ArrayBuffer> =>
  typeof blob.arrayBuffer === "function"
    ? blob.arrayBuffer()
    : new Promise<ArrayBuffer>((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result as ArrayBuffer);
      r.onerror = () => reject(r.error);
      r.readAsArrayBuffer(blob);
    });

async function sha256(file: File): Promise<string> {
  const buf = await readBuffer(file);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function conflict(code: string, message: string, existing: StoredDoc): ApiError {
  return new ApiError(409, message, code, { code, detail: message, existing: publicDoc(existing) });
}

// Mimic the background indexer: queued -> processing -> ready.
function simulateIndexing(doc: StoredDoc) {
  setTimeout(() => {
    if (docs.includes(doc)) doc.status = "processing";
  }, 700);
  setTimeout(() => {
    if (!docs.includes(doc)) return;
    doc.status = "ready";
  }, 2200);
}

// ---------- search (BM25 over the sample chunks) ----------
const tokenize = (s: string): string[] => s.toLowerCase().match(/[a-z0-9]+/g) ?? [];

function search(question: string, k = 4): { doc: StoredDoc; chunk: Chunk }[] {
  const pool = docs.filter((d) => d.status === "ready").flatMap((doc) => doc.chunks.map((chunk) => ({ doc, chunk })));
  if (!pool.length) return [];
  const terms = [...new Set(tokenize(question))];
  const tokens = pool.map((p) => tokenize(p.chunk.text));
  const avg = tokens.reduce((n, t) => n + t.length, 0) / pool.length;
  const df = new Map<string, number>();
  for (const t of terms) df.set(t, tokens.filter((tk) => tk.includes(t)).length);
  const scored = pool.map((p, i) => {
    const tk = tokens[i];
    let score = 0;
    for (const t of terms) {
      const f = tk.filter((x) => x === t).length;
      if (!f) continue;
      const n = df.get(t)!;
      const idf = Math.log(1 + (pool.length - n + 0.5) / (n + 0.5));
      score += (idf * f * 2.2) / (f + 1.2 * (0.25 + (0.75 * tk.length) / avg));
    }
    return { ...p, score };
  });
  return scored
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, k);
}

function toSources(hits: { doc: StoredDoc; chunk: Chunk }[]): Source[] {
  const seen = new Set<string>();
  const out: Source[] = [];
  for (const { doc, chunk } of hits) {
    const key = `${doc.id}:${chunk.page}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ document_id: doc.id, document: doc.name, page: chunk.page, snippet: chunk.text.slice(0, 240) });
  }
  return out;
}

const norm = (q: string) =>
  q
    .toLowerCase()
    .replace(/[^a-z0-9 ]/g, "")
    .replace(/\s+/g, " ")
    .trim();

function answer(question: string): { content: string; sources: Source[] } {
  if (!docs.some((d) => d.status === "ready")) return { content: NO_DOCUMENTS, sources: [] };
  const cached = data.answers.find((a) => norm(a.question) === norm(question));
  // Only replay a recorded answer while the documents it came from are still there.
  if (cached && cached.sources.every((s) => docs.some((d) => d.name === s.document && d.status === "ready" && isOriginal(d)))) {
    const sources = cached.sources.map((s) => ({
      document_id: docs.find((d) => d.name === s.document)?.id ?? null,
      document: s.document,
      page: s.page,
      snippet: s.snippet,
    }));
    return { content: cached.answer, sources };
  }
  const hits = search(question);
  if (!hits.length) {
    return {
      content: "Demo mode has no language model, and nothing in your ready documents matches that question.",
      sources: [],
    };
  }
  return {
    content:
      "Demo mode: there is no language model in this static page, so here are the most relevant passages from your documents. Click a source to read it. Try a suggested question for a full answer, or run the app yourself to get generated answers to anything.",
    sources: toSources(hits),
  };
}

// ---------- the API ----------
export const demoApi = {
  me: async (): Promise<User> => user,
  login: async (): Promise<User> => user,
  register: async (): Promise<User> => user,
  logout: async (): Promise<void> => {},

  documents: async (): Promise<Doc[]> => [...docs].reverse().map(publicDoc),

  upload: async (file: File, replace = false): Promise<Doc> => {
    await wait(250);
    if (!file.name.toLowerCase().endsWith(".pdf")) throw new ApiError(400, "Only PDF files are supported.", "not_pdf");
    const head = new Uint8Array(await readBuffer(file.slice(0, 5)));
    if (new TextDecoder().decode(head) !== "%PDF-") throw new ApiError(400, "That file is not a valid PDF.", "not_pdf");
    if (file.size > 25 * 1024 * 1024) throw new ApiError(413, "The file is larger than the 25 MB limit.", "too_large");

    const hash = await sha256(file);
    const sameContent = docs.find((d) => d.hash === hash);
    if (sameContent) {
      throw conflict("duplicate_content", `You already uploaded this exact file as “${sameContent.name}”.`, sameContent);
    }
    const sameName = docs.find((d) => d.name === file.name);
    if (sameName && !replace) {
      throw conflict(
        "name_exists",
        `A different file named “${file.name}” already exists. Replace it with this one?`,
        sameName
      );
    }
    if (sameName) docs.splice(docs.indexOf(sameName), 1);
    const doc: StoredDoc = {
      id: nextId++,
      name: file.name,
      size: file.size,
      status: "queued",
      error: "",
      pages: null,
      chunk_count: 0,
      uploaded_at: now(),
      hash,
      chunks: [],
    };
    docs.push(doc);
    simulateIndexing(doc);
    return publicDoc(doc);
  },

  deleteDocument: async (id: number): Promise<void> => {
    const i = docs.findIndex((d) => d.id === id);
    if (i < 0) throw new ApiError(404, "Not found.");
    docs.splice(i, 1);
  },

  conversations: async (): Promise<ConversationSummary[]> =>
    [...conversations.values()].map((c) => c.summary).sort((a, b) => b.updated_at.localeCompare(a.updated_at)),

  conversation: async (id: number): Promise<ConversationDetail> => {
    const c = conversations.get(id);
    if (!c) throw new ApiError(404, "Not found.");
    return { ...c.summary, messages: c.messages };
  },

  deleteConversation: async (id: number): Promise<void> => {
    conversations.delete(id);
  },

  ask: async (question: string, conversation?: number) => {
    await wait(700);
    let c = conversation === undefined ? undefined : conversations.get(conversation);
    if (conversation !== undefined && !c) throw new ApiError(404, "Not found.");
    if (!c) {
      const id = nextId++;
      c = { summary: { id, title: question.slice(0, 60), updated_at: now() }, messages: [] };
      conversations.set(id, c);
    }
    const a = answer(question);
    const messages: Message[] = [
      { id: nextMessageId++, role: "user", content: question, sources: [], created_at: now() },
      { id: nextMessageId++, role: "assistant", content: a.content, sources: a.sources, created_at: now() },
    ];
    c.messages.push(...messages);
    c.summary.updated_at = now();
    return { conversation: c.summary, messages };
  },
};
