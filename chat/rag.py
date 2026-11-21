"""Answering a question from one user's documents, and only theirs."""
import logging

from django.conf import settings

from documents.models import Document
from documents.services import user_store
from qa import build_chain
from retrieval import build_hybrid_retriever

log = logging.getLogger(__name__)

NO_DOCUMENTS = (
    "You don't have any processed documents yet. Upload a PDF on the Documents page "
    "and wait until it shows as ready, then ask again."
)


class LLMUnavailable(Exception):
    """The language model could not be reached or failed to answer."""


def get_llm():
    from langchain_community.llms import Ollama

    return Ollama(model=settings.LLM_MODEL, base_url=settings.OLLAMA_BASE_URL, temperature=0)


def _sources(source_documents) -> list[dict]:
    seen, out = set(), []
    for doc in source_documents:
        meta = doc.metadata
        page = meta.get("page")
        page = page + 1 if isinstance(page, int) else None  # stored 0-based
        key = (meta.get("document_id"), page)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "document_id": meta.get("document_id"),
                "document": meta.get("source", "Unknown"),
                "page": page,
                "snippet": " ".join(doc.page_content.split())[:240],
            }
        )
    return out


def answer_question(user, question: str, llm=None):
    """Return ``(answer, sources)`` using only ``user``'s ready documents.

    Isolation is enforced twice: the vector collection is the user's own, and
    both retrievers are further limited to the ids of their ready documents, so
    chunks of a deleted document can never surface.
    """
    ready_ids = list(
        user.documents.filter(status=Document.Status.READY).values_list("id", flat=True)
    )
    if not ready_ids:
        return NO_DOCUMENTS, []
    store = user_store(user.pk)
    where = {"document_id": {"$in": ready_ids}}
    if not store.get(where=where)["ids"]:
        return NO_DOCUMENTS, []

    retriever = build_hybrid_retriever(store, k=settings.TOP_K, where=where)
    try:
        chain = build_chain(llm or get_llm(), retriever)
        out = chain.invoke({"query": question})
    except Exception as exc:  # noqa: BLE001 - connection, model-not-found, timeouts...
        log.exception("language model call failed")
        raise LLMUnavailable(str(exc)) from exc
    return out["result"].strip(), _sources(out["source_documents"])
