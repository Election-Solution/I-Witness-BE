from django.urls import path
from .views import (
    # Public
    CreateReportView,
    UploadMediaView,
    ListReportsView,
    PollingUnitListView,
    # Admin
    AdminListReportsView,
    AdminReportDetailView,
    ResolveReportView,
    ReviewReportView,
    FlagReportView,
    DeleteReportView,
)

# Public
urlpatterns = [
    path("reports/",              ListReportsView.as_view(),    name="reports-list"),
    path("reports/create/",       CreateReportView.as_view(),   name="reports-create"),
    path("reports/<int:pk>/media/",UploadMediaView.as_view(),   name="reports-upload-media"),
    path("polling-units/",        PollingUnitListView.as_view(),name="polling-units-list"),
]

# Admin (all require JWT)
urlpatterns += [
    path("admin/reports/",                AdminListReportsView.as_view(),  name="admin-reports-list"),
    path("admin/reports/<int:pk>/",       AdminReportDetailView.as_view(), name="admin-reports-detail"),
    path("admin/reports/<int:pk>/resolve/",ResolveReportView.as_view(),    name="admin-reports-resolve"),
    path("admin/reports/<int:pk>/review/", ReviewReportView.as_view(),     name="admin-reports-review"),
    path("admin/reports/<int:pk>/flag/",   FlagReportView.as_view(),       name="admin-reports-flag"),
    path("admin/reports/<int:pk>/delete/", DeleteReportView.as_view(),     name="admin-reports-delete"),
]
