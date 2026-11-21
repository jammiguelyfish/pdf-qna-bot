import glob
import os
import shutil

import pytest

pytest.importorskip("chromadb")
pytest.importorskip("pypdf")

from langchain_community.embeddings.fake import DeterministicFakeEmbedding  # noqa: E402
from langchain_community.vectorstores import Chroma  # noqa: E402

from ingestion import (  # noqa: E402
    IngestError,
    chunk_ids,
    hash_file,
    index_pdf,
    list_indexed,
    remove_document,
    sync_directory,
)

ROOT = os.path.dirname(os.path.dirname(__file__))
SAMPLES = sorted(glob.glob(os.path.join(ROOT, "data", "pdfs", "*.pdf")))


class CountingEmbeddings(DeterministicFakeEmbedding):
    """Deterministic fake vectors that also count how many texts were embedded."""

    calls: int = 0

    def embed_documents(self, texts):
        type(self).calls += len(texts)
        return super().embed_documents(texts)


@pytest.fixture
def store(tmp_path):
    CountingEmbeddings.calls = 0
    return Chroma(
        collection_name="test_main",
        persist_directory=str(tmp_path / "db"),
        embedding_function=CountingEmbeddings(size=16),
    )


@pytest.fixture
def pdf_dir(tmp_path):
    d = tmp_path / "pdfs"
    d.mkdir()
    return d


def put(pdf_dir, sample_index, name):
    shutil.copy(SAMPLES[sample_index], pdf_dir / name)
    return pdf_dir / name


def chunk_total(store):
    return len(store.get()["ids"])


def test_samples_exist():
    assert len(SAMPLES) >= 3


def test_first_sync_adds_everything_and_second_sync_does_no_work(store, pdf_dir):
    put(pdf_dir, 0, "a.pdf")
    put(pdf_dir, 1, "b.pdf")
    r1 = sync_directory(store, pdf_dir)
    assert sorted(r1.added) == ["a.pdf", "b.pdf"] and r1.ok
    total, embedded = chunk_total(store), CountingEmbeddings.calls
    assert total > 0 and embedded == total

    r2 = sync_directory(store, pdf_dir)
    assert sorted(r2.unchanged) == ["a.pdf", "b.pdf"]
    assert not (r2.added or r2.updated or r2.removed or r2.reindexed)
    assert CountingEmbeddings.calls == embedded, "nothing should be re-embedded"
    assert chunk_total(store) == total


def test_same_content_under_two_names_is_indexed_once(store, pdf_dir):
    put(pdf_dir, 0, "a.pdf")
    put(pdf_dir, 0, "a_copy.pdf")
    r = sync_directory(store, pdf_dir)
    assert r.added == ["a.pdf"]
    assert r.duplicates == [("a_copy.pdf", "a.pdf")]

    solo = chunk_total(store)
    other = store.__class__(
        collection_name="test_solo", persist_directory=store._persist_directory,
        embedding_function=CountingEmbeddings(size=16),
    )
    index_pdf(other, SAMPLES[0], source="a.pdf")
    assert solo == chunk_total(other), "the duplicate must not add chunks"


def test_edited_file_replaces_its_old_chunks(store, pdf_dir):
    put(pdf_dir, 0, "doc.pdf")
    sync_directory(store, pdf_dir)
    old_hash = hash_file(pdf_dir / "doc.pdf")

    put(pdf_dir, 1, "doc.pdf")  # same name, different content
    r = sync_directory(store, pdf_dir)
    assert r.updated == ["doc.pdf"] and not r.added and not r.removed

    indexed, _ = list_indexed(store)
    assert old_hash not in indexed, "outdated embeddings must be gone"
    assert set(indexed) == {hash_file(pdf_dir / "doc.pdf")}
    assert all(d.complete for d in indexed.values())


def test_deleted_file_is_removed_from_the_index(store, pdf_dir):
    put(pdf_dir, 0, "keep.pdf")
    gone = put(pdf_dir, 1, "gone.pdf")
    sync_directory(store, pdf_dir)
    gone.unlink()

    r = sync_directory(store, pdf_dir)
    assert r.removed == ["gone.pdf"] and r.unchanged == ["keep.pdf"]
    names = {m["source"] for m in store.get(include=["metadatas"])["metadatas"]}
    assert names == {"keep.pdf"}


def test_failure_while_writing_leaves_no_half_indexed_file(store, pdf_dir, monkeypatch):
    path = put(pdf_dir, 0, "a.pdf")
    real_add = store.add_documents

    def write_half_then_die(docs, ids=None, **kw):
        real_add(docs[: len(docs) // 2], ids=ids[: len(docs) // 2])
        raise RuntimeError("embedding service went away")

    monkeypatch.setattr(store, "add_documents", write_half_then_die)
    with pytest.raises(RuntimeError):
        index_pdf(store, path)
    assert chunk_total(store) == 0, "partial chunks must be cleaned up"


def test_crash_without_cleanup_is_detected_and_repaired_on_next_sync(store, pdf_dir):
    path = put(pdf_dir, 0, "a.pdf")
    # Simulate a killed process: only some of the file's chunks were written.
    from ingestion import chunk_pdf

    h = hash_file(path)
    chunks = chunk_pdf(path)
    for c in chunks:
        c.metadata.update({"content_hash": h, "chunk_count": len(chunks), "embedding_model": "all-MiniLM-L6-v2"})
    half = len(chunks) // 2
    store.add_documents(chunks[:half], ids=chunk_ids(h, len(chunks))[:half])
    assert not list_indexed(store)[0][h].complete

    r = sync_directory(store, pdf_dir)
    assert r.reindexed == ["a.pdf"]
    doc = list_indexed(store)[0][h]
    assert doc.complete and doc.found == len(chunks)


def test_one_bad_pdf_is_reported_and_the_rest_still_indexed(store, pdf_dir):
    put(pdf_dir, 0, "good.pdf")
    (pdf_dir / "bad.pdf").write_bytes(b"this is not a pdf")
    r = sync_directory(store, pdf_dir)
    assert r.added == ["good.pdf"]
    assert [name for name, _ in r.failed] == ["bad.pdf"]
    assert not r.ok


def test_changing_the_embedding_model_re_embeds(store, pdf_dir):
    put(pdf_dir, 0, "a.pdf")
    sync_directory(store, pdf_dir, embedding_model="model-1")
    r = sync_directory(store, pdf_dir, embedding_model="model-2")
    assert r.reindexed == ["a.pdf"]
    assert {m["embedding_model"] for m in store.get(include=["metadatas"])["metadatas"]} == {"model-2"}


def test_chunks_from_before_hashes_existed_are_replaced(store, pdf_dir):
    put(pdf_dir, 0, "a.pdf")
    store.add_texts(["old chunk without metadata about hashes"], metadatas=[{"source": "a.pdf", "page": 0}], ids=["legacy-1"])
    sync_directory(store, pdf_dir)
    assert "legacy-1" not in store.get()["ids"]
    assert all("content_hash" in m for m in store.get(include=["metadatas"])["metadatas"])


def test_pdf_without_text_and_encrypted_pdf_are_rejected_with_a_clear_message(store, tmp_path):
    from pypdf import PdfWriter

    blank = tmp_path / "blank.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(str(blank))
    with pytest.raises(IngestError, match="no extractable text"):
        index_pdf(store, blank)

    locked = tmp_path / "locked.pdf"
    w2 = PdfWriter()
    w2.add_blank_page(width=200, height=200)
    w2.encrypt("secret")
    w2.write(str(locked))
    with pytest.raises(IngestError, match="password"):
        index_pdf(store, locked)
    assert chunk_total(store) == 0


def test_indexing_the_same_file_twice_does_not_duplicate_chunks(store):
    n1 = index_pdf(store, SAMPLES[0], source="a.pdf")
    n2 = index_pdf(store, SAMPLES[0], source="a.pdf")
    assert n1 == n2 == chunk_total(store)
    assert remove_document(store, hash_file(SAMPLES[0])) == n1
    assert chunk_total(store) == 0
