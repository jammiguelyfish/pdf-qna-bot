"""Per-user vector collections and document lifecycle."""
import logging

from django.conf import settings

from ingestion import remove_document as remove_chunks
from store import open_store

log = logging.getLogger(__name__)


def collection_name(user_id: int) -> str:
    """Every user's chunks live in a collection of their own."""
    return f"user_{user_id}"


def user_store(user_id: int):
    return open_store(settings.VECTOR_DIR, collection_name(user_id))


def discard(owner_id: int, content_hash: str, file_name: str | None) -> None:
    """Remove a deleted document's chunks and file. Never raises.

    A failure here must not block deleting the document: chunks that outlive
    their document are filtered out of every answer (see chat.rag), so the
    worst case is wasted space, not a leak.
    """
    try:
        remove_chunks(user_store(owner_id), content_hash)
    except Exception:  # noqa: BLE001
        log.exception("could not remove chunks for hash %s", content_hash)
    if file_name:
        try:
            from django.core.files.storage import default_storage

            default_storage.delete(file_name)
        except Exception:  # noqa: BLE001
            log.exception("could not remove file %s", file_name)


def delete_document(doc) -> None:
    owner_id, content_hash, file_name = doc.owner_id, doc.content_hash, doc.file.name
    doc.delete()
    discard(owner_id, content_hash, file_name)
