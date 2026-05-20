from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from authentication.models import PollingUnit, IncidentReport, MediaAttachment, TriageLog, AdminUser


class PollingUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PollingUnit
        # pu_code is the primary key — no separate "id" field
        fields = ["pu_code", "pu_name", "state", "lga", "ward", "latitude", "longitude"]


class MediaAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = MediaAttachment
        fields = ["cloudinary_url", "media_type", "uploaded_at"]


class TriageLogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TriageLog
        fields = ["category", "urgency_score", "ai_summary", "created_at"]

    # Flatten the most useful fields out of raw_ai_response for convenience
    category     = serializers.SerializerMethodField()
    urgency_score= serializers.SerializerMethodField()
    ai_summary   = serializers.SerializerMethodField()

    def get_category(self, obj):
        return obj.raw_ai_response.get("category", "")

    def get_urgency_score(self, obj):
        return obj.raw_ai_response.get("urgency", None)

    def get_ai_summary(self, obj):
        return obj.raw_ai_response.get("summary", "")


# ── Public serializers ────────────────────────────────────────────────────────

class IncidentCreateSerializer(serializers.ModelSerializer):
    """Used by the public to submit a report. No auth required."""

    class Meta:
        model  = IncidentReport
        fields = [
            "polling_unit",     # FK to PollingUnit (pu_code)
            "state",
            "lga",
            "raw_text",         # the incident description
            "reporter_phone",
            "source",           # web | sms
        ]

    def validate(self, attrs):
        if not attrs.get("polling_unit") and not (attrs.get("state") and attrs.get("lga")):
            raise serializers.ValidationError(
                "Provide either a polling_unit or both state and lga."
            )
        return attrs


class MediaUploadSerializer(serializers.ModelSerializer):
    """Attach image/video to an existing incident."""
    media_file = serializers.FileField(write_only=True)

    class Meta:
        model  = MediaAttachment
        fields = ["media_file", "media_type"]

    def validate_media_file(self, value):
        max_size      = 50 * 1024 * 1024   # 50 MB
        allowed_types = [
            "image/jpeg", "image/png", "image/webp",
            "video/mp4",  "video/quicktime", "video/webm",
        ]
        if value.size > max_size:
            raise serializers.ValidationError("File must be under 50 MB.")
        if value.content_type not in allowed_types:
            raise serializers.ValidationError(
                f"Unsupported type: {value.content_type}. "
                "Allowed: JPEG, PNG, WebP, MP4, MOV, WebM."
            )
        return value


class IncidentListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for public list view."""
    polling_unit = PollingUnitSerializer(read_only=True)
    media        = MediaAttachmentSerializer(many=True, read_only=True)
    triage       = serializers.SerializerMethodField()

    class Meta:
        model  = IncidentReport
        fields = [
            "id", "state", "lga", "polling_unit",
            "source", "category", "urgency_score", "ai_summary",
            "status", "report_count", "created_at",
            "media", "triage",
        ]

    def get_triage(self, obj):
        latest = obj.triage_logs.order_by("-created_at").first()
        return TriageLogSerializer(latest).data if latest else None


# ── Admin serializers ─────────────────────────────────────────────────────────

class IncidentDetailSerializer(serializers.ModelSerializer):
    """Full detail for the admin dashboard."""
    polling_unit = PollingUnitSerializer(read_only=True)
    media        = MediaAttachmentSerializer(many=True, read_only=True)
    triage_logs  = TriageLogSerializer(many=True, read_only=True)

    class Meta:
        model  = IncidentReport
        fields = [
            "id", "state", "lga", "polling_unit",
            "reporter_phone", "raw_text", "source",
            "category", "urgency_score", "ai_summary",
            "status", "is_verified",
            "report_count", "cluster_id",
            "created_at", "updated_at",
            "media", "triage_logs",
        ]


class ResolveIncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = IncidentReport
        fields = []   # no body required, just the action

    def update(self, instance, validated_data):
        instance.status      = "closed"
        instance.is_verified = True
        instance.save(update_fields=["status", "is_verified", "updated_at"])
        return instance


class ReviewIncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = IncidentReport
        fields = []

    def update(self, instance, validated_data):
        instance.status = "triaged"
        instance.save(update_fields=["status", "updated_at"])
        return instance


class FlagIncidentSerializer(serializers.ModelSerializer):
    reason = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model  = IncidentReport
        fields = ["reason"]

    def update(self, instance, validated_data):
        # Store flag reason in ai_summary field as a clear marker
        reason = validated_data.get("reason", "")
        instance.ai_summary = f"[FLAGGED] {reason}".strip()
        instance.status     = "closed"
        instance.save(update_fields=["ai_summary", "status", "updated_at"])
        return instance