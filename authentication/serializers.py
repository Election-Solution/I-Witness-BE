from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from authentication.models import PollingUnit, IncidentReport, WardUser, AdminUser

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model

User = get_user_model()


class ReportSubmitSerializer(serializers.Serializer):
    """Incoming report — web or SMS-normalised."""
    # FIX: renamed pu_id → pu_code to match the model's primary key field
    pu_code        = serializers.CharField(max_length=20)
    message        = serializers.CharField()
    reporter_phone = serializers.CharField(required=False, allow_blank=True)
    source         = serializers.ChoiceField(choices=["sms", "web"])

    def validate_pu_code(self, value):
        # FIX: filter on pu_code, not pu_id
        if not PollingUnit.objects.filter(pu_code=value).exists():
            raise serializers.ValidationError(f"Polling Unit '{value}' not found.")
        return value


class IncidentSerializer(serializers.ModelSerializer):
    media              = serializers.SerializerMethodField()
    polling_unit_name  = serializers.CharField(source="polling_unit.name",      read_only=True)
    latitude           = serializers.FloatField(source="polling_unit.latitude",  read_only=True)
    longitude          = serializers.FloatField(source="polling_unit.longitude", read_only=True)

    class Meta:
        model  = IncidentReport
        fields = [
            "id", "polling_unit", "polling_unit_name", "latitude", "longitude",
            "raw_text", "source", "category", "urgency_score", "ai_summary",
            "status", "report_count", "created_at", "media",
        ]

    def get_media(self, obj):
        return [{"url": m.cloudinary_url, "type": m.media_type} for m in obj.media.all()]


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds extra user data to the JWT token payload and login response."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"]        = user.email
        token["full_name"]    = user.full_name
        token["is_staff"]     = user.is_staff
        token["is_superuser"] = user.is_superuser
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = AdminUserSerializer(self.user).data
        return data


class RegisterWardSerializers(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={"input_type": "password"},
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
    )

    class Meta:
        model  = WardUser
        fields = [
            "email", "first_name", "last_name",
            "password", "password_confirm",   
            "is_staff", "is_superuser",
        ]

    def validate(self, attrs):
        
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def get_role(self, obj):
        if obj.is_superuser:
            return "admin"
        elif obj.is_staff:
            return "staff"
        return "citizen"

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model        = AdminUser
        fields       = ["id", "email", "full_name", "role", "created_at"]
        read_only_fields = ["id", "created_at"]