
from django.db.models.signals import post_save
from django.dispatch import receiver
from authentication.models import IncidentReport as Incident


@receiver(post_save, sender=Incident)
def trigger_triage(sender, instance, created, **kwargs):
    """Fire the Celery triage task whenever a new incident is created."""
    if created:
        from authentication.triage import triage_report
        triage_report.delay(instance.pk)