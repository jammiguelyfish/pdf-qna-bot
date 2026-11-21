"""Incremental, restartable PDF ingestion shared by the CLI and the web app.

The vector store itself is the record of what has been indexed. Every chunk
carries three facts in its metadata:

* ``content_hash``: SHA-256 of the PDF's bytes, so identical content is
  recognised under any filename and an edited file is a different document;
* ``chunk_count``: how many chunks the file produced, so a file whose chunks
  were only partly written (crash, Ctrl-C) is noticed and redone;
* ``embedding_model``: so a change of model re-embeds instead of mixing
  incompatible vectors.

Chunk ids are derived from the content hash, so indexing is idempotent, and
nothing is deleted until its replacement is ready to be written.
"""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from store import EMBEDDING_MODEL

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


class IngestError(Exception):
    """A PDF that cannot be indexed, with a message fit to show a user."""


def hash_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_pages(path, source=None) -> list[Document]:
    """One Document per page; ``page`` is 0-based, as PyPDF numbers pages."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    source = source or Path(path).name
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise IngestError("the PDF is password-protected")
        return [
            Document(page_content=page.extract_text() or "", metadata={"source": source, "page": i})
            for i, page in enumerate(reader.pages)
        ]
    except IngestError:
        raise
    except (PdfReadError, ValueError, OSError, KeyError, TypeError) as exc:
        raise IngestError(f"could not read the PDF ({exc})") from exc


def chunk_pdf(path, source=None) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, length_function=len
    )
    return splitter.split_documents(read_pages(path, source))


def chunk_ids(content_hash: str, n: int) -> list[str]:
    return [f"{content_hash[:32]}-{i:05d}" for i in range(n)]


def remove_document(store, content_hash: str) -> int:
    """Delete every chunk of the document with this hash; returns how many."""
    ids = store.get(where={"content_hash": content_hash})["ids"]
    if ids:
        store.delete(ids=ids)
    return len(ids)


def index_pdf(store, path, *, content_hash=None, source=None, extra=None,
              embedding_model=EMBEDDING_MODEL) -> int:
    """Index one PDF and return its chunk count.

    Safe to repeat: any earlier chunks of the same content are replaced. If
    embedding or writing fails, the partly written chunks are removed again
    before the error propagates, so a failure never leaves a half-indexed file
    behind (and if even the cleanup is cut short, ``sync_directory`` notices).
    """
    content_hash = content_hash or hash_file(path)
    chunks = chunk_pdf(path, source)
    if not chunks:
        raise IngestError("no extractable text (is it a scanned PDF?)")
    for chunk in chunks:
        chunk.metadata.update(
            {"content_hash": content_hash, "chunk_count": len(chunks),
             "embedding_model": embedding_model, **(extra or {})}
        )
    remove_document(store, content_hash)
    try:
        store.add_documents(chunks, ids=chunk_ids(content_hash, len(chunks)))
    except BaseException:
        remove_document(store, content_hash)
        raise
    return len(chunks)


@dataclass
class IndexedDoc:
    names: set = field(default_factory=set)
    expected: int = 0
    found: int = 0
    models: set = field(default_factory=set)

    @property
    def complete(self) -> bool:
        return self.found == self.expected


def list_indexed(store):
    """What the store holds: ``({content_hash: IndexedDoc}, legacy_ids)``.

    ``legacy_ids`` are chunks written before hashes were recorded; they cannot
    be matched to a file, so a sync replaces them.
    """
    data = store.get(include=["metadatas"])
    docs, legacy = {}, []
    for cid, meta in zip(data["ids"], data["metadatas"]):
        h = (meta or {}).get("content_hash")
        if not h:
            legacy.append(cid)
            continue
        doc = docs.setdefault(h, IndexedDoc())
        doc.names.add(meta.get("source", ""))
        doc.expected = max(doc.expected, int(meta.get("chunk_count", 0)))
        doc.models.add(meta.get("embedding_model"))
        doc.found += 1
    return docs, legacy


@dataclass
class SyncReport:
    added: list = field(default_factory=list)
    updated: list = field(default_factory=list)      # same name, new content
    reindexed: list = field(default_factory=list)    # unchanged file, redone (incomplete or new model)
    unchanged: list = field(default_factory=list)
    removed: list = field(default_factory=list)      # no longer in the folder
    duplicates: list = field(default_factory=list)   # (name, same content as)
    failed: list = field(default_factory=list)       # (name, reason)

    @property
    def ok(self) -> bool:
        return not self.failed


def sync_directory(store, pdf_dir, *, embedding_model=EMBEDDING_MODEL) -> SyncReport:
    """Make the index match the PDFs in ``pdf_dir``, doing only the needed work.

    Removals run first so outdated chunks disappear even if a later file fails;
    each file is committed on its own, so progress survives a crash and a
    re-run finishes the job. One unreadable PDF is reported, not fatal.
    """
    report = SyncReport()
    on_disk = {}  # content_hash -> path
    for path in sorted(Path(pdf_dir).iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        try:
            h = hash_file(path)
        except OSError as exc:
            report.failed.append((path.name, f"could not read the file ({exc})"))
            continue
        if h in on_disk:
            report.duplicates.append((path.name, on_disk[h].name))
        else:
            on_disk[h] = path

    indexed, legacy_ids = list_indexed(store)
    if legacy_ids:
        store.delete(ids=legacy_ids)

    gone_names, redo = set(), set()
    for h, doc in indexed.items():
        if h not in on_disk:
            remove_document(store, h)
            gone_names |= doc.names
        elif not doc.complete or doc.models != {embedding_model}:
            redo.add(h)
        else:
            report.unchanged.append(on_disk[h].name)

    matched = set()
    for h, path in on_disk.items():
        if h in indexed and h not in redo:
            continue
        try:
            index_pdf(store, path, content_hash=h, embedding_model=embedding_model)
        except Exception as exc:  # one bad file must not stop the rest
            report.failed.append((path.name, str(exc)))
            continue
        if h in redo:
            report.reindexed.append(path.name)
        elif path.name in gone_names:
            report.updated.append(path.name)
            matched.add(path.name)
        else:
            report.added.append(path.name)
    report.removed = sorted(gone_names - matched - {""})
    return report
