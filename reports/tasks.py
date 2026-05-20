"""
Celery tasks for async AI triage processing.

This is a scaffold. Replace the stub logic with a real Anthropic API call
once the ANTHROPIC_API_KEY is configured.

Task flow:
  1. IncidentReport is created → signal fires → triage_report.delay(report_id)
  2. Task fetches the report, calls the AI, updates TriageData
"""
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def triage_report(self, report_id: int):
    """
    Analyse an IncidentReport with an LLM and populate its TriageData.

    Args:
        report_id: PK of the IncidentReport to process.
    """
    from .models import IncidentReport, TriageData

    try:
        report = IncidentReport.objects.select_related("triage", "polling_unit").get(pk=report_id)
    except IncidentReport.DoesNotExist:
        logger.error("triage_report: Report %s not found.", report_id)
        return

    triage, _ = TriageData.objects.get_or_create(report=report)

    if triage.processed:
        logger.info("triage_report: Report %s already processed, skipping.", report_id)
        return

    try:
        ai_result = _call_ai(report)

        triage.category    = ai_result.get("category", "other")
        triage.severity    = ai_result.get("severity", 1)
        triage.ai_summary  = ai_result.get("summary", "")
        triage.is_duplicate= ai_result.get("is_duplicate", False)
        triage.raw_ai_response = ai_result
        triage.processed   = True
        triage.processed_at= timezone.now()
        triage.save()

        logger.info(
            "triage_report: Report %s triaged — category=%s severity=%s",
            report_id, triage.category, triage.severity,
        )

    except Exception as exc:
        logger.exception("triage_report: AI call failed for report %s: %s", report_id, exc)
        raise self.retry(exc=exc)


# ── AI stub — replace with real Anthropic call ───────────────────────────────

def _call_ai(report) -> dict:
    """
    Stub: returns mock data.  Replace body with:

        import anthropic, json
        from django.conf import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=512,
            messages=[{"role": "user", "content": _build_prompt(report)}],
        )
        return json.loads(message.content[0].text)
    """
    description = report.description.lower()

    # Naive keyword severity for the stub
    if any(kw in description for kw in ["gun", "shot", "attack", "violence", "threat"]):
        severity, category = 10, "security"
    elif any(kw in description for kw in ["suppress", "intimidat", "prevent"]):
        severity, category = 8, "security"
    elif any(kw in description for kw in ["missing", "no ballot", "no material"]):
        severity, category = 5, "logistics"
    elif any(kw in description for kw in ["late", "delay", "staff"]):
        severity, category = 3, "logistics"
    else:
        severity, category = 2, "other"

    return {
        "category":     category,
        "severity":     severity,
        "summary":      f"[STUB] Incident at {report.raw_location or 'unknown location'}. "
                        f"Type: {report.incident_type}. Auto-classified as {category} (severity {severity}/10).",
        "is_duplicate": False,
    }


def _build_prompt(report) -> str:
    """Prompt template for the real AI call."""
    location = str(report.polling_unit) if report.polling_unit else report.raw_location
    return f"""You are an election monitoring triage agent. Analyse the following incident report
and respond ONLY with a JSON object matching this schema:
{{
  "category":     "logistics" | "security" | "electoral" | "other",
  "severity":     <integer 1-10>,
  "summary":      "<one sentence plain-English summary>",
  "is_duplicate": <true|false>
}}

--- REPORT ---
Type:        {report.incident_type}
Location:    {location}
Description: {report.description}
Source:      {report.source}
"""
