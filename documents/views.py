import hashlib
import os
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import worker
from .models import Document
from .serializers import DocumentSerializer
from .services import delete_document, discard


def _clean_name(raw: str) -> str:
    """The user's filename as a safe display label (no path, no control chars)."""
    name = os.path.basename((raw or "").replace("\\", "/"))
    return re.sub(r"[\x00-\x1f\x7f]", "", name).strip()[:255]


def _conflict(code: str, message: str, existing: Document) -> Response:
    return Response(
        {"code": code, "detail": message, "existing": DocumentSerializer(existing).data},
        status=status.HTTP_409_CONFLICT,
    )


class DocumentList(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "upload"
            return super().get_throttles()
        return []

    def get(self, request):
        worker.recover_unfinished()
        return Response(DocumentSerializer(request.user.documents.all(), many=True).data)

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"code": "no_file", "detail": "Choose a PDF to upload."}, status=400)
        name = _clean_name(upload.name)
        if not name.lower().endswith(".pdf"):
            return Response({"code": "not_pdf", "detail": "Only PDF files are supported."}, status=400)
        if upload.size > settings.MAX_UPLOAD_BYTES:
            mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
            return Response(
                {"code": "too_large", "detail": f"The file is larger than the {mb} MB limit."}, status=413
            )

        digest, first = hashlib.sha256(), b""
        for block in upload.chunks():
            if not first:
                first = block[:5]
            digest.update(block)
        if first != b"%PDF-":
            return Response({"code": "not_pdf", "detail": "That file is not a valid PDF."}, status=400)
        content_hash = digest.hexdigest()
        replace = str(request.data.get("replace", "")).lower() in ("1", "true", "yes")

        # A failed earlier attempt never blocks a retry of the same file.
        for stale in request.user.documents.filter(status=Document.Status.FAILED).filter(
            content_hash=content_hash
        ):
            delete_document(stale)

        same_content = request.user.documents.filter(content_hash=content_hash).first()
        if same_content:
            return _conflict(
                "duplicate_content",
                f"You already uploaded this exact file as “{same_content.name}”.",
                same_content,
            )
        same_name = request.user.documents.filter(name=name).first()
        if same_name and not replace:
            return _conflict(
                "name_exists",
                f"A different file named “{name}” already exists. Replace it with this one?",
                same_name,
            )

        upload.seek(0)
        old = None
        try:
            with transaction.atomic():
                if same_name:
                    old = (same_name.owner_id, same_name.content_hash, same_name.file.name)
                    same_name.delete()
                doc = Document.objects.create(
                    owner=request.user,
                    name=name,
                    file=upload,
                    content_hash=content_hash,
                    size=upload.size,
                )
        except IntegrityError:  # an identical upload won the race
            existing = request.user.documents.filter(content_hash=content_hash).first()
            if existing:
                return _conflict("duplicate_content", "That file was just uploaded.", existing)
            raise
        if old:
            discard(*old)
        worker.recover_unfinished()
        worker.enqueue(doc.pk)
        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class DocumentDetail(APIView):
    def get(self, request, pk):
        return Response(DocumentSerializer(get_object_or_404(request.user.documents, pk=pk)).data)

    def delete(self, request, pk):
        delete_document(get_object_or_404(request.user.documents, pk=pk))
        return Response(status=status.HTTP_204_NO_CONTENT)
