"""Chat: answers come only from the asking user's ready documents."""
from unittest import mock

from django.contrib.auth import get_user_model
from langchain_community.llms.fake import FakeListLLM

from chat import rag
from chat.models import Conversation, Message
from documents import services
from documents.models import Document
from documents.tests import TempDirs, pdf_bytes

User = get_user_model()


def fake_llm(text="Mocked answer."):
    return FakeListLLM(responses=[text] * 50)


class ChatTests(TempDirs):
    def ask(self, question, **extra):
        with mock.patch.object(rag, "get_llm", return_value=fake_llm()):
            return self.client.post("/api/chat/", {"question": question, **extra}, content_type="application/json")

    def test_without_documents_it_says_so_and_never_calls_the_model(self):
        with mock.patch.object(rag, "get_llm", side_effect=AssertionError("must not be called")):
            r = self.client.post("/api/chat/", {"question": "What day is it?"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["messages"][1]["content"], rag.NO_DOCUMENTS)
        self.assertEqual(r.json()["messages"][1]["sources"], [])

    def test_answer_comes_with_sources_that_name_file_and_page(self):
        self.post("korea.pdf", pdf_bytes(1))
        r = self.ask("How many nights are we staying in Busan?")
        self.assertEqual(r.status_code, 200)
        user_msg, bot_msg = r.json()["messages"]
        self.assertEqual(user_msg["role"], "user")
        self.assertEqual(bot_msg["content"], "Mocked answer.")
        self.assertTrue(bot_msg["sources"])
        for s in bot_msg["sources"]:
            self.assertEqual(s["document"], "korea.pdf")
            self.assertGreaterEqual(s["page"], 1)
            self.assertTrue(s["snippet"])

    def test_follow_up_questions_extend_the_same_conversation(self):
        self.post("korea.pdf", pdf_bytes(1))
        first = self.ask("Where do we land?").json()
        convo = first["conversation"]["id"]
        self.ask("And the next day?", conversation=convo)
        detail = self.client.get(f"/api/conversations/{convo}/").json()
        self.assertEqual([m["role"] for m in detail["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertEqual(len(self.client.get("/api/conversations/").json()), 1)

    def test_validation(self):
        self.assertEqual(self.ask("   ").status_code, 400)
        self.assertEqual(self.ask("x" * 1001).status_code, 400)
        self.assertEqual(self.ask("hi", conversation=9999).status_code, 404)
        self.assertEqual(Message.objects.count(), 0)

    def test_model_outage_returns_503_and_saves_nothing(self):
        self.post("korea.pdf", pdf_bytes(1))
        with mock.patch.object(rag, "get_llm", side_effect=ConnectionError("connection refused")):
            r = self.client.post("/api/chat/", {"question": "Where?"}, content_type="application/json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("Ollama", r.json()["detail"])
        self.assertEqual(Conversation.objects.count(), 0)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.ask("hi").status_code, 403)
        self.assertEqual(self.client.get("/api/conversations/").status_code, 403)


class IsolationTests(TempDirs):
    def sources_for(self, user, question):
        with mock.patch.object(rag, "get_llm", return_value=fake_llm()):
            r = self.client.post("/api/chat/", {"question": question}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        return r.json()["messages"][1]

    def test_a_user_never_gets_another_users_chunks_in_answers(self):
        # Alice has the Korea itinerary; Bob has the Tokyo one.
        self.post("korea.pdf", pdf_bytes(1))
        self.client.force_login(self.bob)
        self.post("tokyo.pdf", pdf_bytes(2))

        # "Busan" appears only in Alice's file. Bob asking about it must not reach it.
        bob_ids = set(self.bob.documents.values_list("id", flat=True))
        msg = self.sources_for(self.bob, "How many nights are we staying in Busan?")
        self.assertTrue(msg["sources"], "bob has a ready document, so something is retrieved")
        for s in msg["sources"]:
            self.assertIn(s["document_id"], bob_ids)
            self.assertEqual(s["document"], "tokyo.pdf")
            self.assertNotIn("Busan", s["snippet"])

        # ... and the reverse: Alice asking about Tokyo only ever sees her own file.
        self.client.force_login(self.alice)
        msg = self.sources_for(self.alice, "Which transit card should I get in Tokyo?")
        self.assertEqual({s["document"] for s in msg["sources"]}, {"korea.pdf"})

    def test_a_user_with_no_documents_gets_nothing_even_if_others_have_some(self):
        self.post("korea.pdf", pdf_bytes(1))
        self.client.force_login(self.bob)
        msg = self.sources_for(self.bob, "How many nights are we staying in Busan?")
        self.assertEqual(msg["content"], rag.NO_DOCUMENTS)
        self.assertEqual(msg["sources"], [])

    def test_chunks_of_a_deleted_document_never_surface(self):
        self.post("korea.pdf", pdf_bytes(1))
        # Chunks left behind by a document that no longer exists (say a failed cleanup).
        store = services.user_store(self.alice.pk)
        store.add_texts(
            ["Busan orphaned secret chunk that should never be shown"],
            metadatas=[{"source": "ghost.pdf", "page": 0, "document_id": 99999, "content_hash": "x", "chunk_count": 1}],
            ids=["ghost-1"],
        )
        msg = self.sources_for(self.alice, "How many nights are we staying in Busan?")
        self.assertTrue(msg["sources"])
        self.assertNotIn("ghost.pdf", {s["document"] for s in msg["sources"]})

    def test_documents_still_processing_are_not_searched(self):
        self.post("korea.pdf", pdf_bytes(1))
        Document.objects.update(status=Document.Status.PROCESSING)
        msg = self.sources_for(self.alice, "Busan?")
        self.assertEqual(msg["content"], rag.NO_DOCUMENTS)

    def test_conversations_are_private(self):
        self.post("korea.pdf", pdf_bytes(1))
        convo = self.sources_for(self.alice, "Where?") and Conversation.objects.get().pk
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get("/api/conversations/").json(), [])
        self.assertEqual(self.client.get(f"/api/conversations/{convo}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/conversations/{convo}/").status_code, 404)
        with mock.patch.object(rag, "get_llm", return_value=fake_llm()):
            r = self.client.post(
                "/api/chat/", {"question": "Sneaky", "conversation": convo}, content_type="application/json"
            )
        self.assertEqual(r.status_code, 404, "bob must not be able to post into alice's conversation")
        self.assertEqual(Message.objects.filter(conversation_id=convo).count(), 2)

    def test_owner_can_delete_a_conversation(self):
        self.post("korea.pdf", pdf_bytes(1))
        self.sources_for(self.alice, "Where?")
        convo = Conversation.objects.get().pk
        self.assertEqual(self.client.delete(f"/api/conversations/{convo}/").status_code, 204)
        self.assertEqual(Message.objects.count(), 0)
