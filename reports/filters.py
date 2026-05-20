import django_filters
from authentication.models import IncidentReport as Incident


class IncidentFilter(django_filters.FilterSet):
    state        = django_filters.CharFilter(lookup_expr="iexact")
    lga          = django_filters.CharFilter(lookup_expr="iexact")
    pu_code      = django_filters.CharFilter(field_name="polling_unit__pu_code", lookup_expr="iexact")
    status       = django_filters.MultipleChoiceFilter(choices=Incident.STATUS_CHOICES)
    category     = django_filters.MultipleChoiceFilter(choices=Incident.CATEGORY_CHOICES)
    source       = django_filters.ChoiceFilter(choices=Incident.SOURCE_OPTIONS)
    min_urgency  = django_filters.NumberFilter(field_name="urgency_score", lookup_expr="gte")
    created_after  = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model  = Incident
        fields = ["status", "category", "source", "state", "lga"]