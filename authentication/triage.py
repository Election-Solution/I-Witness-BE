import time
import json

from celery import shared_task
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from datetime import timedelta 
from .models import IncidentReport, TriageLog

from google import genai
from google.genai import types
 
client = genai.Client(api_key=settings.GEMINI_API_KEY)
 


# genai.configure(api_key=settings.GEMINI_API_KEY)
# model = genai.GenerativeModel("gemini-1.5-flash")

TRIAGE_PROMPT = """
You are an election incident triage AI for Nigeria. Analyze the report and respond ONLY with valid JSON.

Report: "{text}"
Polling Unit: {pu_code}

Respond with:
{{
  "category": "logistics|security|staff_conduct|general",
  "urgency": <integer 1-10>,
  "summary": "<one sentence, max 20 words>",
  "keywords": ["<key term>", ...]
}}

Urgency guide: 1-3=minor, 4-6=moderate, 7-9=serious, 10=life-threatening.
"""

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def triage_report(self, incident_id):
    try:
        incident = IncidentReport.objects.select_related("polling_unit").get(id=incident_id)
        prompt = TRIAGE_PROMPT.format(
            text=incident.raw_text,
            pu_code=incident.polling_unit.pu_code if incident.polling_unit else "unknown",
        )

        start = time.time()
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        elapsed_ms = int((time.time() - start) * 1000)

        raw_json = response.text.strip().strip("```json").strip("```")
        result = json.loads(raw_json)

        # Deduplication logic
        existing = IncidentReport.objects.filter(
            polling_unit=incident.polling_unit,
            category=result["category"],
            status__in=["pending", "triaged"],
            created_at__gte=incident.created_at - timedelta(hours=2),  
        ).exclude(id=incident.id).first()

        if existing:
            existing.report_count += 1
            existing.save(update_fields=["report_count", "updated_at"])
            incident.cluster_id = str(existing.id)
        else:
            incident.cluster_id = str(incident.id)

        incident.category     = result["category"]
        incident.urgency_score = result["urgency"]
        incident.ai_summary   = result["summary"]
        incident.status       = "triaged"
        incident.save()

        TriageLog.objects.create(
            incident=incident,
            raw_ai_response=result,
            prompt_used=prompt,
            processing_time_ms=elapsed_ms,
        )

        _push_to_dashboard(incident)

    except Exception as exc:
        raise self.retry(exc=exc)


def _push_to_dashboard(incident):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "incidents",
        {
            "type": "incident.update",
            "data": {
                "id":           incident.id,
                "latitude":     float(incident.polling_unit.latitude)  if incident.polling_unit.latitude  else None,
                "longitude":    float(incident.polling_unit.longitude) if incident.polling_unit.longitude else None,
                "category":     incident.category,
                "urgency":      incident.urgency_score,
                "summary":      incident.ai_summary,
                "report_count": incident.report_count,
            },
        },
    )