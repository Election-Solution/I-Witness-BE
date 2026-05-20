
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404

from authentication.models import IncidentReport, PollingUnit, MediaAttachment
from .serializers import (
    IncidentCreateSerializer,
    IncidentListSerializer,
    IncidentDetailSerializer,
    MediaUploadSerializer,
    ResolveIncidentSerializer,
    ReviewIncidentSerializer,
    FlagIncidentSerializer,
    PollingUnitSerializer,
)
from .filters import IncidentFilter
from .permissions import IsAdminUser, IsSuperAdmin


# ── Public endpoints ──────────────────────────────────────────────────────────

class CreateReportView(generics.CreateAPIView):
    """
    POST /api/v1/reports/create/
    Submit a new incident report. No authentication required.

    Body (JSON or multipart/form-data):
      - polling_unit   (pu_code, optional)
      - state          (required if no polling_unit)
      - lga            (required if no polling_unit)
      - raw_text       (required — the incident description)
      - reporter_phone (optional)
      - source         (web | sms, default: web)
    """
    permission_classes = [AllowAny]
    serializer_class   = IncidentCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = serializer.save()
        return Response(
            {
                "id":      incident.pk,
                "message": "Report submitted successfully. Thank you.",
                "status":  incident.status,
            },
            status=status.HTTP_201_CREATED,
        )


class UploadMediaView(APIView):
    """
    POST /api/v1/reports/<pk>/media/
    Attach an image or video to an existing incident. No authentication required.

    Body (multipart/form-data):
      - media_file  (JPEG, PNG, WebP, MP4, MOV, WebM — max 50 MB)
      - media_type  (image | video)
    """
    permission_classes = [AllowAny]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request, pk):
        incident = get_object_or_404(IncidentReport, pk=pk)
        serializer = MediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        media_file  = serializer.validated_data["media_file"]
        media_type  = serializer.validated_data.get("media_type", "image")

        # Upload to Cloudinary via django-cloudinary-storage
        import cloudinary.uploader
        upload_result = cloudinary.uploader.upload(
            media_file,
            folder="watchdog/incidents",
            resource_type="auto",
        )

        attachment = MediaAttachment.objects.create(
            incident             = incident,
            cloudinary_url       = upload_result["secure_url"],
            cloudinary_public_id = upload_result["public_id"],
            media_type           = media_type,
        )

        return Response(
            {"id": attachment.pk, "media_url": attachment.cloudinary_url},
            status=status.HTTP_201_CREATED,
        )


class ListReportsView(generics.ListAPIView):
    """
    GET /api/v1/reports/
    Paginated public list of incidents.

    Filter params: state, lga, pu_code, status, category, source,
                   min_urgency, created_after, created_before
    Search:        ?search=<text>  (searches raw_text)
    Ordering:      ?ordering=urgency_score | -urgency_score | created_at | -created_at
    """
    permission_classes = [AllowAny]
    serializer_class   = IncidentListSerializer
    filterset_class    = IncidentFilter
    search_fields      = ["raw_text", "state", "lga", "polling_unit__name"]
    ordering_fields    = ["created_at", "urgency_score"]
    ordering           = ["-created_at"]

    def get_queryset(self):
        return (
            IncidentReport.objects
            .select_related("polling_unit")
            .prefetch_related("media", "triage_logs")
        )


class PollingUnitListView(generics.ListAPIView):
    """
    GET /api/v1/polling-units/
    Populate state/LGA/ward/PU dropdowns on the report form.

    Query params: state, lga, ward
    """
    permission_classes = [AllowAny]
    serializer_class   = PollingUnitSerializer
    search_fields      = ["state", "lga", "ward", "pu_code", "name"]

    def get_queryset(self):
        qs    = PollingUnit.objects.all()
        state = self.request.query_params.get("state")
        lga   = self.request.query_params.get("lga")
        ward  = self.request.query_params.get("ward")
        if state: qs = qs.filter(state__iexact=state)
        if lga:   qs = qs.filter(lga__iexact=lga)
        if ward:  qs = qs.filter(ward__iexact=ward)
        return qs


# ── Admin endpoints (JWT required) ───────────────────────────────────────────

class AdminListReportsView(generics.ListAPIView):
    """
    GET /api/v1/admin/reports/
    Full incident list for the triage dashboard.
    Supports all the same filters as the public list.
    """
    permission_classes = [IsAdminUser]
    serializer_class   = IncidentDetailSerializer
    filterset_class    = IncidentFilter
    search_fields      = ["raw_text", "state", "lga", "reporter_phone"]
    ordering_fields    = ["created_at", "urgency_score", "status"]
    ordering           = ["-urgency_score", "-created_at"]

    def get_queryset(self):
        return (
            IncidentReport.objects
            .select_related("polling_unit")
            .prefetch_related("media", "triage_logs")
        )


class AdminReportDetailView(generics.RetrieveAPIView):
    """GET /api/v1/admin/reports/<pk>/"""
    permission_classes = [IsAdminUser]
    serializer_class   = IncidentDetailSerializer

    def get_queryset(self):
        return IncidentReport.objects.select_related("polling_unit").prefetch_related("media", "triage_logs")


class ResolveReportView(generics.UpdateAPIView):
    """PATCH /api/v1/admin/reports/<pk>/resolve/ — mark as closed + verified."""
    permission_classes = [IsAdminUser]
    serializer_class   = ResolveIncidentSerializer
    http_method_names  = ["patch"]

    def get_queryset(self):
        return IncidentReport.objects.all()

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        incident = serializer.save()
        return Response(IncidentDetailSerializer(incident).data)


class ReviewReportView(generics.UpdateAPIView):
    """PATCH /api/v1/admin/reports/<pk>/review/ — move to triaged/under-review."""
    permission_classes = [IsAdminUser]
    serializer_class   = ReviewIncidentSerializer
    http_method_names  = ["patch"]

    def get_queryset(self):
        return IncidentReport.objects.all()

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        incident = serializer.save()
        return Response(IncidentDetailSerializer(incident).data)


class FlagReportView(generics.UpdateAPIView):
    """
    PATCH /api/v1/admin/reports/<pk>/flag/
    Body (optional): { "reason": "duplicate / spam / false report" }
    """
    permission_classes = [IsAdminUser]
    serializer_class   = FlagIncidentSerializer
    http_method_names  = ["patch"]

    def get_queryset(self):
        return IncidentReport.objects.all()

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        incident = serializer.save()
        return Response(IncidentDetailSerializer(incident).data)


class DeleteReportView(APIView):
    """
    DELETE /api/v1/admin/reports/<pk>/
    Soft delete: sets status="closed". Hard delete restricted to superadmins (?hard=true).
    """
    permission_classes = [IsAdminUser]

    def delete(self, request, pk):
        incident    = get_object_or_404(IncidentReport, pk=pk)
        hard_delete = request.query_params.get("hard", "false").lower() == "true"

        if hard_delete:
            if not IsSuperAdmin().has_permission(request, self):
                return Response(
                    {"detail": "Hard delete is restricted to superadmins."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            incident.delete()
            return Response({"detail": "Incident permanently deleted."}, status=status.HTTP_204_NO_CONTENT)

        incident.status = "closed"
        incident.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Incident closed (soft delete)."}, status=status.HTTP_200_OK)