"""Upload, duplicate handling, lifecycle and per-user isolation.

These run against a real Chroma index in a temporary directory, with fake
embeddings (no model download) and the indexer running inline.
"""
import glob
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from langchain_community.embeddings.fake import DeterministicFakeEmbedding

from documents import services, worker
from documents.models import Document
from ingestion import IngestError
from store import open_store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = sorted(glob.glob(os.path.join(ROOT, "data", "pdfs", "*.pdf")))

User = get_user_model()
FAKE = DeterministicFakeEmbedding(size=16)


def pdf_bytes(i):
    with open(SAMPLES[i], "rb") as f:
        return f.read()


def upload(name, data):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


class TempDirs(TestCase):
    """Fresh upload and vector directories, and fake embeddings, for each test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        override = override_settings(
            MEDIA_ROOT=os.path.join(self.tmp, "uploads"), VECTOR_DIR=os.path.join(self.tmp, "chroma")
        )
        override.enable()
        self.addCleanup(override.disable)
        patcher = mock.patch("store.get_embeddings", return_value=FAKE)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        worker._recovered = False
        self.alice = User.objects.create_user("alice", password="pw-alice-12345")
        self.bob = User.objects.create_user("bob", password="pw-bob-12345")
        self.client.force_login(self.alice)

    def post(self, name, data, **extra):
        return self.client.post("/api/documents/", {"file": upload(name, data), **extra})

    def chunks(self, user):
        return services.user_store(user.pk).get()["ids"]


class UploadTests(TempDirs):
    def test_upload_indexes_the_pdf(self):
        r = self.post("trip.pdf", pdf_bytes(0))
        self.assertEqual(r.status_code, 201)
        doc = Document.objects.get(pk=r.json()["id"])
        self.assertEqual(doc.status, Document.Status.READY)
        self.assertGreater(doc.chunk_count, 0)
        self.assertGreater(doc.pages, 0)
        self.assertEqual(len(self.chunks(self.alice)), doc.chunk_count)

    def test_identical_file_under_another_name_is_a_duplicate(self):
        self.post("trip.pdf", pdf_bytes(0))
        before = len(self.chunks(self.alice))
        r = self.post("trip-copy.pdf", pdf_bytes(0))
        self.assertEqual(r.status_code, 409)
        body = r.json()
        self.assertEqual(body["code"], "duplicate_content")
        self.assertEqual(body["existing"]["name"], "trip.pdf")
        self.assertEqual(len(self.chunks(self.alice)), before)
        self.assertEqual(self.alice.documents.count(), 1)

    def test_same_name_different_content_asks_before_replacing(self):
        self.post("trip.pdf", pdf_bytes(0))
        r = self.post("trip.pdf", pdf_bytes(1))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["code"], "name_exists")
        self.assertEqual(self.alice.documents.get().content_hash, Document.objects.get().content_hash)

    def test_replace_swaps_the_content_and_removes_the_old_embeddings(self):
        old = self.post("trip.pdf", pdf_bytes(0)).json()["id"]
        old_hash = Document.objects.get(pk=old).content_hash
        old_file = Document.objects.get(pk=old).file.path

        r = self.post("trip.pdf", pdf_bytes(1), replace="true")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.alice.documents.count(), 1)
        new = self.alice.documents.get()
        self.assertNotEqual(new.content_hash, old_hash)

        metas = services.user_store(self.alice.pk).get(include=["metadatas"])["metadatas"]
        self.assertEqual({m["content_hash"] for m in metas}, {new.content_hash})
        self.assertFalse(os.path.exists(old_file), "the old file should be deleted too")

    def test_rejects_non_pdfs_and_missing_files(self):
        self.assertEqual(self.post("notes.txt", b"hello").status_code, 400)
        r = self.post("fake.pdf", b"not really a pdf")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "not_pdf")
        self.assertEqual(self.client.post("/api/documents/", {}).status_code, 400)

    @override_settings(MAX_UPLOAD_BYTES=1000)
    def test_rejects_oversized_files(self):
        r = self.post("big.pdf", pdf_bytes(0))
        self.assertEqual(r.status_code, 413)
        self.assertEqual(self.alice.documents.count(), 0)

    def test_filename_is_sanitized(self):
        r = self.post("../../etc/evil\x00name.pdf", pdf_bytes(0))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["name"], "evilname.pdf")
        doc = Document.objects.get()
        self.assertTrue(os.path.realpath(doc.file.path).startswith(os.path.realpath(self.tmp)))

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/documents/").status_code, 403)
        self.assertEqual(self.post("a.pdf", pdf_bytes(0)).status_code, 403)


class FailureTests(TempDirs):
    def test_unreadable_pdf_is_marked_failed_with_a_reason_and_can_be_retried(self):
        body = b"%PDF-1.4 this starts like a pdf but is not one"
        r = self.post("broken.pdf", body)
        self.assertEqual(r.status_code, 201)
        doc = Document.objects.get()
        self.assertEqual(doc.status, Document.Status.FAILED)
        self.assertIn("could not read", doc.error.lower())
        self.assertEqual(len(self.chunks(self.alice)), 0)

        # uploading the same bytes again is allowed, not blocked as a duplicate
        r2 = self.post("broken.pdf", body)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(self.alice.documents.count(), 1)

    def test_embedding_failure_halfway_leaves_nothing_behind(self):
        real = services.user_store(self.alice.pk).add_documents

        def half_then_die(self_, docs, ids=None, **kw):
            real(docs[: len(docs) // 2], ids=ids[: len(docs) // 2])
            raise RuntimeError("embedding service went away")

        with mock.patch("langchain_community.vectorstores.Chroma.add_documents", half_then_die):
            self.post("trip.pdf", pdf_bytes(0))
        doc = Document.objects.get()
        self.assertEqual(doc.status, Document.Status.FAILED)
        self.assertEqual(len(self.chunks(self.alice)), 0, "partial chunks must be cleaned up")

    def test_interrupted_documents_are_picked_up_again_after_a_restart(self):
        self.post("trip.pdf", pdf_bytes(0))
        doc = Document.objects.get()
        services.user_store(self.alice.pk).delete(ids=self.chunks(self.alice))
        Document.objects.filter(pk=doc.pk).update(status=Document.Status.PROCESSING)  # "crashed" mid-job

        worker._recovered = False  # a new process
        self.assertEqual(self.client.get("/api/documents/").status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.READY)
        self.assertEqual(len(self.chunks(self.alice)), doc.chunk_count)

    def test_deleting_a_document_while_it_is_being_indexed_leaves_no_chunks(self):
        doc = Document.objects.create(
            owner=self.alice, name="x.pdf", content_hash="h" * 64, size=1, file=upload("x.pdf", pdf_bytes(0))
        )
        real_index = worker.index_pdf

        def delete_then_index(*a, **kw):
            Document.objects.filter(pk=doc.pk).delete()  # the user deletes it mid-job
            return real_index(*a, **kw)

        with mock.patch.object(worker, "index_pdf", delete_then_index):
            worker.process(doc.pk)
        self.assertEqual(len(self.chunks(self.alice)), 0)


class DeleteAndIsolationTests(TempDirs):
    def test_delete_removes_row_file_and_chunks(self):
        r = self.post("trip.pdf", pdf_bytes(0))
        doc = Document.objects.get(pk=r.json()["id"])
        path = doc.file.path
        self.assertEqual(self.client.delete(f"/api/documents/{doc.pk}/").status_code, 204)
        self.assertFalse(Document.objects.exists())
        self.assertFalse(os.path.exists(path))
        self.assertEqual(len(self.chunks(self.alice)), 0)

    def test_users_only_see_their_own_documents(self):
        mine = self.post("mine.pdf", pdf_bytes(0)).json()["id"]
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get("/api/documents/").json(), [])
        self.assertEqual(self.client.get(f"/api/documents/{mine}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/documents/{mine}/").status_code, 404)
        self.assertTrue(Document.objects.filter(pk=mine).exists(), "bob must not be able to delete it")

    def test_two_users_can_upload_the_same_file_and_keep_separate_indexes(self):
        self.post("trip.pdf", pdf_bytes(0))
        self.client.force_login(self.bob)
        r = self.post("trip.pdf", pdf_bytes(0))
        self.assertEqual(r.status_code, 201, "a duplicate is only a duplicate within one account")
        self.assertEqual(len(self.chunks(self.alice)), len(self.chunks(self.bob)))

        # deleting bob's copy leaves alice's index intact
        self.client.delete(f"/api/documents/{r.json()['id']}/")
        self.assertEqual(len(self.chunks(self.bob)), 0)
        self.assertGreater(len(self.chunks(self.alice)), 0)

    def test_collections_are_separate_per_user(self):
        self.post("trip.pdf", pdf_bytes(0))
        other = open_store(services.settings.VECTOR_DIR, services.collection_name(self.bob.pk))
        self.assertEqual(other.get()["ids"], [])
        hits = other.similarity_search("anything at all", k=5)
        self.assertEqual(hits, [], "a query on bob's collection must never return alice's chunks")
