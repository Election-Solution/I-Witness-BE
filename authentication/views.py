from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated

from .models import IncidentReport, PollingUnit
from .serializers import (
    ReportSubmitSerializer,
    IncidentSerializer,
    RegisterWardSerializers,
    CustomTokenObtainPairSerializer,
    AdminUserSerializer,
)


User = get_user_model()


def index(request):
    return render(request, 'index.html')

class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/
    Body: { "email": "...", "password": "..." }
    Returns: { "access": "...", "refresh": "...", "user": {...} }
    """
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            try:
                user = User.objects.get(email=request.data.get("email"))
                user.last_activity = timezone.now()
                # only save if the field exists (AdminUser doesn't have last_activity)
                if hasattr(user, "last_activity"):
                    user.save(update_fields=["last_activity"])
            except User.DoesNotExist:
                pass
        return response



class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Body: { "refresh": "..." }
    Blacklists the refresh token.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Successfully logged out."}, status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MeView(APIView):
    """GET /api/v1/auth/me/ — returns the current admin user's profile."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(AdminUserSerializer(request.user).data)


class TokenRefreshView(BaseTokenRefreshView):
    """POST /api/v1/auth/refresh/ — wraps SimpleJWT's built-in refresh."""
    pass


class ReportView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from .triage import triage_report
        serializer = ReportSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        # FIX: was pu_id — now pu_code to match model
        pu = PollingUnit.objects.get(pu_code=data["pu_code"])

        incident = IncidentReport.objects.create(
            polling_unit=pu,
            raw_text=data["message"],
            reporter_phone=data.get("reporter_phone", ""),
            source=data["source"],
            status="pending",
        )

        triage_report.delay(incident.id)

        return Response({"id": incident.id, "status": "received"}, status=status.HTTP_201_CREATED)



class SMSWebhookView(APIView):
    """Africa's Talking / Twilio POST endpoint."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from .triage import triage_report
        phone   = request.data.get("from", "")
        message = request.data.get("text", "")
        pu_code, body = self._parse_sms(message)

        # FIX: key is pu_code now
        normalized = {"pu_code": pu_code, "message": body, "reporter_phone": phone, "source": "sms"}
        serializer = ReportSubmitSerializer(data=normalized)

        if serializer.is_valid():
            pu = PollingUnit.objects.get(pu_code=pu_code)
            incident = IncidentReport.objects.create(
                polling_unit=pu, raw_text=body,
                reporter_phone=phone, source="sms",
            )
            triage_report.delay(incident.id)
            return Response({"message": "Report received. Thank you."})

        return Response({"message": "Could not process report."}, status=400)

    def _parse_sms(self, text):
        """Extract PU code from SMS. Format: 'PU 24/01/01 No security here...'"""
        import re
        match = re.search(r"PU\s*([\d/]+)", text, re.IGNORECASE)
        if match:
            pu_code = match.group(1)
            body    = text[match.end():].strip()
            return pu_code, body
        return "", text



class IncidentListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs          = IncidentReport.objects.select_related("polling_unit").prefetch_related("media")
        urgency_min = request.query_params.get("urgency_min")
        category    = request.query_params.get("category")
        if urgency_min:
            qs = qs.filter(urgency_score__gte=int(urgency_min))
        if category:
            qs = qs.filter(category=category)
        return Response(IncidentSerializer(qs[:100], many=True).data)


class RegisterWard(generics.CreateAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class   = RegisterWardSerializers

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        refresh["email"]      = user.email
        refresh["first_name"] = user.first_name
        refresh["last_name"]  = user.last_name

        return Response({
            "access":     str(refresh.access_token),
            "refresh":    str(refresh),
            "email":      user.email,
            "first_name": user.first_name,
            "last_name":  user.last_name,
            "staff":      user.is_staff,
            "admin":      user.is_admin,   
        }, status=status.HTTP_201_CREATED)  