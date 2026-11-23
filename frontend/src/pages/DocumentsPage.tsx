import { DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, DEMO, Doc, DocStatus, api } from "../api";
import { sampleFiles } from "../demo/demoApi";

interface Notice {
  id: number;
  kind: "duplicate" | "name_exists" | "error";
  message: string;
  file: File;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const badge: Record<DocStatus, string> = {
  queued: "bg-slate-100 text-slate-700",
  processing: "bg-amber-100 text-amber-800",
  ready: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

const label: Record<DocStatus, string> = {
  queued: "Queued",
  processing: "Processing…",
  ready: "Ready",
  failed: "Failed",
};

let noticeSeq = 0;

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [loadError, setLoadError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try {
      setDocs(await api.documents());
      setLoadError("");
    } catch (e: any) {
      setLoadError(e.message);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // While anything is still being indexed, keep checking on it.
  const busy = docs?.some((d) => d.status === "queued" || d.status === "processing");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(reload, 2000);
    return () => clearInterval(t);
  }, [busy, reload]);

  function addNotice(kind: Notice["kind"], message: string, file: File) {
    setNotices((n) => [...n, { id: ++noticeSeq, kind, message, file }]);
  }

  async function uploadOne(file: File, replace = false) {
    setUploading((n) => n + 1);
    try {
      await api.upload(file, replace);
      await reload();
    } catch (e: any) {
      if (e instanceof ApiError && e.code === "duplicate_content") addNotice("duplicate", e.message, file);
      else if (e instanceof ApiError && e.code === "name_exists") addNotice("name_exists", e.message, file);
      else addNotice("error", `${file.name}: ${e.message}`, file);
    } finally {
      setUploading((n) => n - 1);
    }
  }

  async function handleFiles(files: FileList | File[]) {
    for (const file of Array.from(files)) await uploadOne(file);
  }

  function dismiss(id: number) {
    setNotices((n) => n.filter((x) => x.id !== id));
  }

  async function replace(notice: Notice) {
    dismiss(notice.id);
    await uploadOne(notice.file, true);
  }

  async function remove(doc: Doc) {
    if (!window.confirm(`Delete “${doc.name}”? Its indexed content is removed too.`)) return;
    try {
      await api.deleteDocument(doc.id);
    } catch (e: any) {
      addNotice("error", e.message, new File([], doc.name));
    }
    await reload();
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-xl p-8 text-center bg-white ${
          dragging ? "border-brand-500 bg-brand-50" : "border-slate-300"
        }`}
      >
        <p className="text-slate-700">Drag PDFs here, or</p>
        <button
          className="mt-2 bg-brand-500 text-white px-4 py-2 rounded-md hover:bg-brand-700"
          onClick={() => input.current?.click()}
        >
          Choose files
        </button>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          data-testid="file-input"
          onChange={(e) => {
            if (e.target.files) handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-slate-500 mt-3">
          PDFs with selectable text, up to 25 MB each. Your documents are private to your account.
        </p>
        {uploading > 0 && <p className="text-sm text-brand-700 mt-2">Uploading…</p>}
        {DEMO && (
          <p className="text-xs text-slate-600 mt-3">
            Try the warnings: download a sample, then upload it again (renamed or not) to get the duplicate notice.
            Uploaded files are checked but not read in this demo; search covers the samples only.
            <span className="block mt-1">
              {sampleFiles.map((f, i) => (
                <span key={f.name}>
                  {i > 0 && " · "}
                  <a className="underline text-brand-700" href={f.url} download>
                    {f.name}
                  </a>
                </span>
              ))}
            </span>
          </p>
        )}
      </div>

      {notices.map((n) => (
        <div
          key={n.id}
          role="alert"
          className={`rounded-lg border p-3 text-sm flex items-start gap-3 ${
            n.kind === "error"
              ? "bg-red-50 border-red-200 text-red-800"
              : "bg-amber-50 border-amber-200 text-amber-900"
          }`}
        >
          <div className="flex-1">
            <div className="font-medium">
              {n.kind === "duplicate" && "Already uploaded"}
              {n.kind === "name_exists" && "A file with this name exists"}
              {n.kind === "error" && "Upload problem"}
            </div>
            <div>{n.message}</div>
          </div>
          {n.kind === "name_exists" && (
            <button className="bg-amber-600 text-white rounded px-3 py-1 hover:bg-amber-700" onClick={() => replace(n)}>
              Replace
            </button>
          )}
          <button className="border rounded px-3 py-1 bg-white hover:bg-slate-50" onClick={() => dismiss(n.id)}>
            {n.kind === "name_exists" ? "Cancel" : "Dismiss"}
          </button>
        </div>
      ))}

      {loadError && (
        <div role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
          {loadError}
        </div>
      )}

      <div className="bg-white border rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500 bg-slate-50">
            <tr>
              <th className="px-4 py-2">Document</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 hidden sm:table-cell">Pages</th>
              <th className="px-4 py-2 hidden sm:table-cell">Size</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {docs?.map((d) => (
              <tr key={d.id} className="border-t align-top">
                <td className="px-4 py-2 break-all">{d.name}</td>
                <td className="px-4 py-2">
                  <span className={`inline-block rounded-full px-2 py-0.5 text-xs ${badge[d.status]}`}>
                    {label[d.status]}
                  </span>
                  {d.status === "failed" && d.error && <div className="text-xs text-red-700 mt-1">{d.error}</div>}
                </td>
                <td className="px-4 py-2 hidden sm:table-cell">{d.pages ?? "–"}</td>
                <td className="px-4 py-2 hidden sm:table-cell">{formatSize(d.size)}</td>
                <td className="px-4 py-2 text-right">
                  <button className="text-red-700 hover:underline" onClick={() => remove(d)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {docs && docs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No documents yet. Upload a PDF to get started.
                </td>
              </tr>
            )}
            {!docs && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
