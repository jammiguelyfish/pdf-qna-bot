from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import rag
from .models import Conversation, Message
from .serializers import ConversationDetailSerializer, ConversationSerializer, MessageSerializer

MAX_QUESTION_CHARS = 1000


class ConversationList(APIView):
    def get(self, request):
        return Response(ConversationSerializer(request.user.conversations.all(), many=True).data)


class ConversationDetail(APIView):
    def get(self, request, pk):
        convo = get_object_or_404(request.user.conversations, pk=pk)
        return Response(ConversationDetailSerializer(convo).data)

    def delete(self, request, pk):
        get_object_or_404(request.user.conversations, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class Ask(APIView):
    throttle_scope = "chat"

    def post(self, request):
        question = str(request.data.get("question", "")).strip()
        if not question:
            return Response({"detail": "Type a question first."}, status=400)
        if len(question) > MAX_QUESTION_CHARS:
            return Response(
                {"detail": f"Questions are limited to {MAX_QUESTION_CHARS} characters."}, status=400
            )

        convo_id = request.data.get("conversation")
        convo = get_object_or_404(request.user.conversations, pk=convo_id) if convo_id else None

        history = (
            list(convo.messages.order_by("-created_at", "-id").values_list("role", "content")[: rag.HISTORY_MESSAGES])[::-1]
            if convo
            else []
        )
        try:
            answer, sources = rag.answer_question(request.user, question, history=history)
        except rag.LLMUnavailable:
            return Response(
                {"detail": "The language model isn't reachable right now. Is Ollama running?"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        with transaction.atomic():
            if convo is None:
                convo = Conversation.objects.create(owner=request.user, title=question[:120])
            else:
                convo.save()  # bump updated_at so it sorts first
            user_msg = Message.objects.create(conversation=convo, role=Message.Role.USER, content=question)
            bot_msg = Message.objects.create(
                conversation=convo, role=Message.Role.ASSISTANT, content=answer, sources=sources
            )
        return Response(
            {
                "conversation": ConversationSerializer(convo).data,
                "messages": MessageSerializer([user_msg, bot_msg], many=True).data,
            }
        )
