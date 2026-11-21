"""Opening the persisted Chroma index, shared by the CLI and the web app."""
from functools import lru_cache

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_COLLECTION = "langchain"  # the collection the CLI has always used


@lru_cache(maxsize=1)
def get_embeddings():
    """The embedding model, loaded once per process (loading takes seconds)."""
    from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def open_store(persist_directory, collection=DEFAULT_COLLECTION, embeddings=None):
    """Open (creating if needed) one Chroma collection.

    The web app gives every user a collection of their own; retrieval, keyword
    search and deletion all work on a single collection, so one user's chunks
    are never visible to another's queries.
    """
    from langchain_community.vectorstores import Chroma

    return Chroma(
        collection_name=collection,
        persist_directory=str(persist_directory),
        embedding_function=embeddings or get_embeddings(),
    )
