import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ConversationSummary, DEMO, Message, Source, api } from "../api";
import { demoQuestions } from "../demo/demoApi";

function SourceList({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!sources.length) return null;
  return (
    <div className="mt-2">
      <div className="text-xs text-slate-500 mb-1">Sources</div>
      <div className="flex flex-wrap gap-1">
        {sources.map((s, i) => (
          <button
            key={i}
            onClick={() => setOpen(open === i ? null : i)}
            className="text-xs border rounded-full px-2 py-0.5 bg-white hover:bg-brand-50"
          >
            {s.document}
            {s.page ? ` · p.${s.page}` : ""}
          </button>
        ))}
      </div>
      {open !== null && (
        <blockquote className="mt-2 text-xs text-slate-600 border-l-4 border-brand-100 pl-3">
          {sources[open].snippet}
          {sources[open].snippet.length >= 240 && "…"}
        </blockquote>
      )}
    </div>
  );
}

export default function ChatPage() {
  const [convos, setConvos] = useState<ConversationSummary[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [hasReady, setHasReady] = useState<boolean | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const loadConvos = useCallback(() => api.conversations().then(setConvos).catch(() => {}), []);

  useEffect(() => {
    loadConvos();
    api
      .documents()
      .then((d) => setHasReady(d.some((x) => x.status === "ready")))
      .catch(() => setHasReady(null));
  }, [loadConvos]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, sending]);

  async function open(id: number | null) {
    setActive(id);
    setError("");
    setMessages(id === null ? [] : (await api.conversation(id)).messages);
  }

  async function remove(id: number) {
    if (!window.confirm("Delete this conversation?")) return;
    await api.deleteConversation(id);
    if (active === id) await open(null);
    loadConvos();
  }

  function send(e: FormEvent) {
    e.preventDefault();
    return submit(question);
  }

  async function submit(raw: string) {
    const text = raw.trim();
    if (!text || sending) return;
    setSending(true);
    setError("");
    // show the question immediately; the saved copy replaces it on success
    const pending: Message = { id: -1, role: "user", content: text, sources: [], created_at: "" };
    setMessages((m) => [...m, pending]);
    setQuestion("");
    try {
      const r = await api.ask(text, active ?? undefined);
      setActive(r.conversation.id);
      setMessages((m) => [...m.filter((x) => x.id !== -1), ...r.messages]);
      loadConvos();
    } catch (err: any) {
      setMessages((m) => m.filter((x) => x.id !== -1));
      setQuestion(text);
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="h-full flex gap-4 min-h-0">
      <aside className="w-56 shrink-0 hidden md:flex flex-col min-h-0">
        <button
          className="mb-2 border rounded-md py-2 bg-white hover:bg-brand-50 text-sm"
          onClick={() => open(null)}
        >
          + New chat
        </button>
        <div className="flex-1 overflow-y-auto space-y-1">
          {convos.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center rounded-md text-sm ${
                active === c.id ? "bg-brand-50 text-brand-700" : "hover:bg-white"
              }`}
            >
              <button className="flex-1 text-left px-3 py-2 truncate" onClick={() => open(c.id)} title={c.title}>
                {c.title}
              </button>
              <button
                aria-label="Delete conversation"
                className="px-2 text-slate-400 hover:text-red-700 opacity-0 group-hover:opacity-100"
                onClick={() => remove(c.id)}
              >
                ×
              </button>
            </div>
          ))}
          {convos.length === 0 && <p className="text-xs text-slate-500 px-1">No conversations yet.</p>}
        </div>
      </aside>

      <section className="flex-1 flex flex-col min-h-0 bg-white border rounded-xl shadow-sm">
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-slate-500 mt-12 space-y-2">
              <p>Ask a question about your documents.</p>
              {DEMO && (
                <div className="flex flex-wrap justify-center gap-2 pt-2" aria-label="Suggested questions">
                  {demoQuestions.map((q) => (
                    <button
                      key={q}
                      onClick={() => submit(q)}
                      className="text-sm border rounded-full px-3 py-1 bg-white text-slate-700 hover:bg-brand-50"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}
              {hasReady === false && (
                <p className="text-sm">
                  You have no processed documents yet.{" "}
                  <Link to="/documents" className="text-brand-700 underline">
                    Upload a PDF
                  </Link>{" "}
                  first.
                </p>
              )}
            </div>
          )}
          {messages.map((m, i) => (
            <div key={`${m.id}-${i}`} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap ${
                  m.role === "user" ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-900"
                }`}
              >
                {m.content}
                {m.role === "assistant" && <SourceList sources={m.sources} />}
              </div>
            </div>
          ))}
          {sending && <div className="text-sm text-slate-500">Searching your documents…</div>}
          <div ref={bottom} />
        </div>
        {error && (
          <div role="alert" className="mx-4 mb-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
            {error}
          </div>
        )}
        <form onSubmit={send} className="border-t p-3 flex gap-2">
          <input
            className="flex-1 border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
            placeholder="Ask about your documents…"
            value={question}
            maxLength={1000}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label="Question"
          />
          <button
            disabled={sending || !question.trim()}
            className="bg-brand-500 text-white px-4 py-2 rounded-md hover:bg-brand-700 disabled:opacity-60"
          >
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
