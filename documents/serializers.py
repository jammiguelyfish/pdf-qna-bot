from rest_framework import serializers

from .models import Document


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ["id", "name", "size", "status", "error", "pages", "chunk_count", "uploaded_at"]
        read_only_fields = fields
