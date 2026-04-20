from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

import os
import uuid

# write your models here.
def report_media_file_path(instance, filename):
    ext = os.path.splitext(filename)[1]
    filename = f'{uuid.uuid4()}{ext}'
    return os.path.join('reports', filename)

class PollingUnit(models.Model):
    """ Pre-loaded data for all Nigerian Polling Units."""
    pu_code = models.CharField(max_length=20, unique=True, primary_key=True)
    name = models.CharField(max_length=150)
    lga = models.CharField(max_length=150)
    state =  models.CharField(max_length=150)
    ward = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
            return f"{self.pu_code} - {self.name}"

class Incident(models.Model):
    """ The core report submitted by citizens. """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('investigating', 'Investigating'),
        ('resolved', 'Resolved')
    ]

    SOURCE_OPTIONS = [
        ('sms', 'SMS'),
        ('web', 'Web')
    ]
    
    CATEGORY_CHOICES = [
        ('logistics', 'Logistics (Materials/Staff)'),
        ('security', 'Security Threat'),
        ('fraud', 'Malpractice/Fraud'),
        ('technical', 'BVAS/Technical Issues'),
        ('other', 'Other'),
    ]
    
    polling_unit = models.ForeignKey(PollingUnit, on_delete=models.CASCADE, related_name='incidents')  
    reporter_phone = models.CharField(max_length=20, blank=True, null=True) # For SMS tracking
    
    raw_text = models.TextField(blank=True, null=True) # Store the original text for AI processing and audit trail
    media_url = models.URLField(max_length=500, blank=True, null=True) # cloudinary link or similar
    source = models.CharField(choices=SOURCE_OPTIONS, default='sms') # not required for web submissions but useful for SMS tracking


    # AI Triage Fields (to be populated async task)
    urgency_score =  models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(10)])
    category = models.CharField(choices=CATEGORY_CHOICES, default='others')
    ai_summary = models.CharField(max_length=255, blank=True, null=True)

    # Admin Management Fields
    is_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default='pending')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    

    class Meta:
        ordering = ['-urgency_score', '-created_at']

    def __str__(self):
        return f"{self.category.upper()} at {self.polling_unit_id} (Urgency: {self.urgency_score})"