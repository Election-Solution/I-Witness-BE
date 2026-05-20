from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import AbstractUser, AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.conf import settings

import os
import uuid

from grpc import Status

# write your models here.
class AdminUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", AdminUser.Role.SUPERADMIN)
        return self.create_user(email, password, **extra_fields)


class AdminUser(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        TRIAGE_AGENT = "triage_agent", "Triage Agent"
        CSO_ADMIN    = "cso_admin",    "CSO Admin"
        SUPERADMIN   = "superadmin",   "Super Admin"

    email      = models.EmailField(unique=True)
    full_name  = models.CharField(max_length=255)
    role       = models.CharField(max_length=20, choices=Role.choices, default=Role.TRIAGE_AGENT)
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    groups = models.ManyToManyField(
        "auth.Group",
        blank=True,
        related_name="admin_users",        # FIX
        help_text="The groups this user belongs to.",
        verbose_name="groups",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        blank=True,
        related_name="admin_users",        # FIX
        help_text="Specific permissions for this user.",
        verbose_name="user permissions",
    )

    objects = AdminUserManager()

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table     = "admin_users"
        verbose_name = "Admin User"

    def __str__(self):
        return f"{self.full_name} <{self.email}> [{self.role}]"


def report_media_file_path(instance, filename):
    ext = os.path.splitext(filename)[1]
    filename = f'{uuid.uuid4()}{ext}'
    return os.path.join('reports', filename)


class WardUser(AbstractUser):
    email        = models.EmailField(max_length=254, unique=True)
    first_name   = models.CharField(max_length=50)
    last_name    = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=20, blank=True)   
    is_active    = models.BooleanField(default=False)             
    is_staff     = models.BooleanField(default=False)
    created_at   = models.DateField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)           
    is_email_verified = models.BooleanField(default=False)

    groups = models.ManyToManyField(
        "auth.Group",
        blank=True,
        related_name="ward_users",         # FIX
        help_text="The groups this user belongs to.",
        verbose_name="groups",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        blank=True,
        related_name="ward_users",         # FIX
        help_text="Specific permissions for this user.",
        verbose_name="user permissions",
    )

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    @property
    def is_admin(self):
        return self.is_superuser

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class UserRole(models.Model):
    class Role(models.TextChoices):
        OBSERVER  = "observer",  "Observer"
        AGENT     = "agent",     "Ward Agent"
        OFFICER   = "officer",   "Electoral Officer"

    ward = models.ForeignKey(WardUser, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OBSERVER)  

    def __str__(self):
        return f"{self.ward} — {self.role}"


class PollingUnit(models.Model):
    """Pre-loaded data for all Nigerian Polling Units."""
    pu_code   = models.CharField(max_length=20, unique=True, primary_key=True)  
    pu_name      = models.CharField(max_length=150)
    lga       = models.CharField(max_length=150)
    state     = models.CharField(max_length=150)
    ward      = models.CharField(max_length=100)
    latitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        return f"{self.pu_code} - {self.pu_name}"
    
    class Meta:
        db_table  = "polling_units"
        ordering  = ["state", "lga", "ward"]
        indexes   = [
            models.Index(fields=["state", "lga"]),
            models.Index(fields=["pu_code"]),
        ]


class IncidentReport(models.Model):
    STATUS_CHOICES = [
        ("pending",  "Pending"),
        ("reviewing", "Reviewing"),
        ("escalated", "Escalated"),
        ("resolved",  "Resolved"),
        ("flagged",   "Flagged"),
        ("triaged",  "Triaged"),
        ("verified", "Verified"),
        ("closed",   "Closed"),
    ]

    SOURCE_OPTIONS = [
        ('sms', 'SMS'),
        ('web', 'Web'),
    ]

    CATEGORY_CHOICES = [
        ('logistics', 'Logistics (Materials/Staff)'),
        ('security',  'Security Threat'),
        ('fraud',     'Malpractice/Fraud'),
        ('technical', 'BVAS/Technical Issues'),
        ('other',     'Other'),
    ]

    INCIDENT_CHOICES = [
        ('missing_materials', 'Missing Materials'),
        ('delayed_staff', 'Delayed Staff'),
        ('security_threat', 'Security Threat'),
        ('voter_suppression', 'Voter Suppression'),
        ('other', 'Other'),    ]

    state          = models.CharField(max_length=100)
    lga            = models.CharField(max_length=100)   
    polling_unit   = models.ForeignKey(PollingUnit, on_delete=models.CASCADE, related_name='incidents')
    
    reporter_name = models.CharField(max_length=255, blank=True)
    reporter_phone = models.CharField(max_length=20, blank=True, null=True)
    
    raw_text       = models.TextField(blank=True, null=True)
    
    raw_location = models.CharField(max_length=500, blank=True)

    # AI triage fields (populated by async Celery task)
    urgency_score  = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    category       = models.CharField(choices=CATEGORY_CHOICES, max_length=20, default='other')  # FIX: 'other' not 'others'
    ai_summary     = models.CharField(max_length=255, blank=True, null=True)
    report_count   = models.IntegerField(default=1)
    cluster_id     = models.CharField(max_length=50, blank=True)
    
    # Incident details
    incident_type  = models.CharField(max_length=30, choices=INCIDENT_CHOICES, default='other')
    description    = models.TextField()
    source         = models.CharField(max_length=5, choices=SOURCE_OPTIONS, default='sms')
    status         = models.CharField(max_length=15, choices=STATUS_CHOICES, default="pending")

    # Admin management
    reviewed_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewed_reports"
    )
    review_notes   = models.TextField(blank=True)
    is_deleted     = models.BooleanField(default=False)   # Soft delete

    is_verified    = models.BooleanField(default=False)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    # Media — stored in Cloudinary via DEFAULT_FILE_STORAGE
    media_file     = models.FileField(upload_to="incidents/media/", null=True, blank=True)
    media_url      = models.URLField(blank=True)   # Populated after Cloudinary upload


    def __str__(self):
        return f"{self.category.upper()} at {self.polling_unit_id} (Urgency: {self.urgency_score})"

    class Meta:
        db_table  = "incident_reports"
        ordering  = ["-created_at"]
        indexes   = [
            models.Index(fields=["status"]),
            models.Index(fields=["incident_type"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["is_deleted"]),
        ]


class MediaAttachment(models.Model):
    incident = models.ForeignKey(IncidentReport, related_name="media", on_delete=models.CASCADE)
    cloudinary_url = models.URLField()
    cloudinary_public_id = models.CharField(max_length=200)
    media_type = models.CharField(max_length=10, choices=[("image", "Image"), ("video", "Video")])
    uploaded_at = models.DateTimeField(auto_now_add=True)

class TriageLog(models.Model):
    incident = models.ForeignKey(IncidentReport, related_name="triage_logs", on_delete=models.CASCADE)
    raw_ai_response = models.JSONField()
    prompt_used = models.TextField()
    processing_time_ms = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)



class TriageData(models.Model):
    """AI-generated analysis linked to an IncidentReport."""

    class Category(models.TextChoices):
        LOGISTICS = "logistics", "Logistics"
        SECURITY  = "security",  "Security"
        ELECTORAL = "electoral", "Electoral Process"
        OTHER     = "other",     "Other"

    class Severity(models.IntegerChoices):
        LOW      = 1, "Low"
        MODERATE = 5, "Moderate"
        HIGH     = 8, "High"
        CRITICAL = 10, "Critical"

    report      = models.OneToOneField(
        IncidentReport, on_delete=models.CASCADE, related_name="triage"
    )
    category    = models.CharField(max_length=20, choices=Category.choices, blank=True)
    severity    = models.IntegerField(default=0)          # 1-10 from AI
    ai_summary  = models.TextField(blank=True)
    is_duplicate= models.BooleanField(default=False)
    processed   = models.BooleanField(default=False)      # False until Celery runs
    processed_at= models.DateTimeField(null=True, blank=True)
    raw_ai_response = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "triage_data"

    def __str__(self):
        return f"Triage #{self.report_id} — {self.category} severity={self.severity}"
