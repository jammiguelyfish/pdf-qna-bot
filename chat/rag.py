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


HISTORY_MESSAGES = 4  # the last two exchanges are enough to resolve "and the next day?"
MAX_HISTORY_CHARS = 300
MAX_STANDALONE_CHARS = 300

CONDENSE_PROMPT = """Rewrite the follow-up question so that it can be understood without the conversation.

Rules:
- Replace pronouns and references ("it", "that day", "the next one") with what they refer to.
- Keep every name, number and date from the follow-up question.
- If the follow-up question already makes sense on its own, repeat it unchanged.
- Do not answer the question. Output only the rewritten question, on one line.

Conversation:
{history}

Follow-up question: {question}

Rewritten question:"""


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


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_HISTORY_CHARS else text[: MAX_HISTORY_CHARS - 1] + "…"


def standalone_question(llm, history, question: str) -> str:
    """Rewrite a follow-up so retrieval does not depend on earlier messages.

    ``history`` is a list of ``(role, text)`` pairs, oldest first. With no history
    the question is returned untouched and the model is not called. If the model
    returns nothing usable, the original question is used.
    """
    if not history:
        return question
    lines = "\n".join(
        f"{'User' if role == 'user' else 'Assistant'}: {_clip(text)}"
        for role, text in history[-HISTORY_MESSAGES:]
    )
    rewritten = str(llm.invoke(CONDENSE_PROMPT.format(history=lines, question=question))).strip()
    rewritten = rewritten.removeprefix("Rewritten question:").strip().strip('"')
    if not rewritten or "\n" in rewritten or len(rewritten) > MAX_STANDALONE_CHARS:
        return question
    return rewritten


def answer_question(user, question: str, llm=None, history=None):
    """Return ``(answer, sources)`` using only ``user``'s ready documents.

    ``history`` (earlier ``(role, text)`` pairs of the conversation) lets a
    follow-up question be rewritten into one that stands alone before searching.

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
        llm = llm or get_llm()
        query = standalone_question(llm, history or [], question)
        chain = build_chain(llm, retriever)
        out = chain.invoke({"query": query})
    except Exception as exc:  # noqa: BLE001 - connection, model-not-found, timeouts...
        log.exception("language model call failed")
        raise LLMUnavailable(str(exc)) from exc
    return out["result"].strip(), _sources(out["source_documents"])
