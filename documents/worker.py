"""Background indexing on a single worker thread.

One thread keeps writes to the vector index serial and the embedding model
unshared. Document status in the database is the job record: after a restart,
anything still queued or processing is picked up again (indexing is
idempotent). This suits one server process; with several, use a real queue such
as Celery or RQ.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections

from ingestion import IngestError, index_pdf
from ingestion import remove_document as remove_chunks

from .models import Document
from .services import user_store

log = logging.getLogger(__name__)

_executor = None
_lock = threading.Lock()
_recovered = False


def enqueue(doc_id: int) -> None:
    global _executor
    if settings.INDEX_INLINE:
        process(doc_id)
        return
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indexer")
    _executor.submit(process, doc_id)


def recover_unfinished() -> None:
    """Once per process, re-queue documents a previous process left unfinished."""
    global _recovered
    with _lock:
        if _recovered:
            return
        _recovered = True
    pending = list(Document.objects.filter(status__in=[Document.Status.QUEUED, Document.Status.PROCESSING]))
    for doc in pending:
        Document.objects.filter(pk=doc.pk).update(status=Document.Status.QUEUED)
        enqueue(doc.pk)


def process(doc_id: int) -> None:
    try:
        _process(doc_id)
    except Exception:  # noqa: BLE001
        log.exception("indexing document %s crashed", doc_id)
    finally:
        close_old_connections()


def _process(doc_id: int) -> None:
    # claim the job atomically so two threads can't index the same document
    claimed = Document.objects.filter(pk=doc_id, status=Document.Status.QUEUED).update(
        status=Document.Status.PROCESSING
    )
    if not claimed:
        return
    doc = Document.objects.get(pk=doc_id)
    store = user_store(doc.owner_id)
    try:
        chunks = index_pdf(
            store,
            doc.file.path,
            content_hash=doc.content_hash,
            source=doc.name,
            extra={"document_id": doc.pk},
        )
        from pypdf import PdfReader

        pages = len(PdfReader(doc.file.path).pages)
    except IngestError as exc:
        _finish(doc.pk, Document.Status.FAILED, error=str(exc))
        return
    except Exception:  # noqa: BLE001
        log.exception("indexing %s failed", doc.pk)
        _finish(doc.pk, Document.Status.FAILED, error="Indexing failed. Delete the file and upload it again.")
        return

    if not _finish(doc.pk, Document.Status.READY, pages=pages, chunk_count=chunks):
        # deleted while it was being indexed: take the new chunks out again
        remove_chunks(store, doc.content_hash)


def _finish(doc_id: int, status, error: str = "", pages=None, chunk_count: int = 0) -> bool:
    """Record the outcome; False if the document no longer exists."""
    return bool(
        Document.objects.filter(pk=doc_id).update(
            status=status, error=error, pages=pages, chunk_count=chunk_count
        )
    )
