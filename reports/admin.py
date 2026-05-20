from django.contrib import admin
from authentication.models import IncidentReport, MediaAttachment, TriageLog, PollingUnit


class MediaAttachmentInline(admin.TabularInline):
    model   = MediaAttachment
    extra   = 0
    readonly_fields = ["cloudinary_url", "cloudinary_public_id", "media_type", "uploaded_at"]


class TriageLogInline(admin.StackedInline):
    model   = TriageLog
    extra   = 0
    readonly_fields = ["raw_ai_response", "prompt_used", "processing_time_ms", "created_at"]


@admin.register(IncidentReport)
class IncidentAdmin(admin.ModelAdmin):
    list_display   = ["id", "category", "urgency_score", "status", "state", "lga", "source", "created_at"]
    list_filter    = ["status", "category", "source", "is_verified"]
    search_fields  = ["raw_text", "state", "lga", "reporter_phone"]
    readonly_fields= ["created_at", "updated_at", "urgency_score", "ai_summary", "category"]
    inlines        = [MediaAttachmentInline, TriageLogInline]
    date_hierarchy = "created_at"
    ordering       = ["-urgency_score", "-created_at"]


@admin.register(PollingUnit)
class PollingUnitAdmin(admin.ModelAdmin):
    list_display  = ["pu_code", "pu_name", "ward", "lga", "state"]
    list_filter   = ["state"]
    search_fields = ["pu_code", "pu_name", "ward", "lga", "state"]
 