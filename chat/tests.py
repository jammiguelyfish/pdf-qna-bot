"""Chat: answers come only from the asking user's ready documents."""
from typing import ClassVar
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


class RecordingLLM(FakeListLLM):
    """A scripted model that remembers every prompt it was given."""

    def _call(self, prompt, *args, **kwargs):
        RecordingLLM.prompts.append(prompt)
        return super()._call(prompt, *args, **kwargs)

    prompts: ClassVar[list] = []

    @classmethod
    def condense_prompts(cls):
        return [p for p in cls.prompts if p.startswith("Rewrite the follow-up")]


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


class FollowUpTests(TempDirs):
    """A follow-up is rewritten into a standalone question before searching."""

    def ask_recording(self, question, rewrite, **extra):
        """Ask with a model that rewrites to ``rewrite``; return (response, prompts, query used)."""
        RecordingLLM.prompts = []
        llm = RecordingLLM(responses=[rewrite, "Mocked answer."])
        seen = {}
        real_chain = rag.build_chain

        def spy(llm_, retriever):
            chain = real_chain(llm_, retriever)

            class Spy:  # chains are pydantic models, so wrap instead of patching invoke
                @staticmethod
                def invoke(inputs, *a, **k):
                    seen.update(inputs)
                    return chain.invoke(inputs, *a, **k)

            return Spy

        with mock.patch.object(rag, "get_llm", return_value=llm), mock.patch.object(rag, "build_chain", spy):
            r = self.client.post("/api/chat/", {"question": question, **extra}, content_type="application/json")
        return r, RecordingLLM.condense_prompts(), seen.get("query")

    def test_first_question_is_searched_as_typed_without_an_extra_model_call(self):
        self.post("korea.pdf", pdf_bytes(1))
        r, prompts, query = self.ask_recording("Where do we land?", "unused")
        self.assertEqual(query, "Where do we land?")
        self.assertEqual(prompts, [])

    def test_follow_up_is_rewritten_using_the_earlier_messages(self):
        self.post("korea.pdf", pdf_bytes(1))
        convo = self.ask_recording("Where do we land?", "Seoul.")[0].json()["conversation"]["id"]  # first turn: no rewrite, so this is the answer
        r, prompts, query = self.ask_recording(
            "And the next day?", "Rewritten question: What do we do the day after landing in Seoul?", conversation=convo
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(query, "What do we do the day after landing in Seoul?")
        self.assertEqual(len(prompts), 1)
        self.assertIn("Where do we land?", prompts[0])
        self.assertIn("Seoul.", prompts[0])
        # what the user typed is what gets saved and shown
        self.assertEqual(r.json()["messages"][0]["content"], "And the next day?")

    def test_unusable_rewrites_fall_back_to_the_original_question(self):
        history = [("user", "Where do we land?"), ("assistant", "Seoul.")]
        for bad in ["", "   ", "line one\nline two", "x" * 500]:
            llm = FakeListLLM(responses=[bad])
            self.assertEqual(rag.standalone_question(llm, history, "And then?"), "And then?", repr(bad[:10]))

    def test_only_the_most_recent_messages_and_clipped_text_are_sent(self):
        history = [("user", f"question {i}") for i in range(10)] + [("assistant", "long " * 500)]
        RecordingLLM.prompts = []
        rag.standalone_question(RecordingLLM(responses=["ok"]), history, "and then?")
        seen = RecordingLLM.condense_prompts()
        self.assertNotIn("question 5", seen[0])
        self.assertIn("question 8", seen[0])
        self.assertLess(len(seen[0]), len(rag.CONDENSE_PROMPT) + 4 * 320 + 100)

    def test_another_users_conversation_history_is_never_used(self):
        self.post("korea.pdf", pdf_bytes(1))
        convo = self.ask_recording("Secret question?", "unused")[0].json()["conversation"]["id"]
        self.client.logout()
        other = User.objects.create_user("zed", password="a-long-passphrase-9")
        self.client.force_login(other)
        r = self.client.post(
            "/api/chat/", {"question": "hi", "conversation": convo}, content_type="application/json"
        )
        self.assertEqual(r.status_code, 404)


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


class RateLimitTests(TempDirs):
    """Chat and uploads are throttled per user (the limits are lowered for the test)."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        patcher = mock.patch(
            "rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES", {"chat": "2/min", "upload": "2/hour"}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(cache.clear)

    def test_chat_is_rate_limited_per_user(self):
        def ask(client):
            return client.post("/api/chat/", {"question": "hi"}, content_type="application/json")

        with mock.patch.object(rag, "get_llm", return_value=fake_llm()):
            self.assertEqual(ask(self.client).status_code, 200)
            self.assertEqual(ask(self.client).status_code, 200)
            self.assertEqual(ask(self.client).status_code, 429)
            # another user has their own allowance
            self.client.force_login(self.bob)
            self.assertEqual(ask(self.client).status_code, 200)

    def test_uploads_are_rate_limited(self):
        from documents.tests import upload

        codes = [self.client.post("/api/documents/", {"file": upload(f"n{i}.txt", b"x")}).status_code for i in range(3)]
        self.assertEqual(codes, [400, 400, 429])
