from django.urls import path
from .views import *

# write your urls here.
urlpatterns = [
    path('', index, name='index'),

    path("report/", ReportView.as_view()),
    path("sms/", SMSWebhookView.as_view()),
    path("incidents/", IncidentListView.as_view()),
    
    path("login/",   LoginView.as_view(),        name="auth-login"),
    path("logout/",  LogoutView.as_view(),        name="auth-logout"),
    path("refresh/", TokenRefreshView.as_view(),  name="auth-refresh"),
    path("me/",      MeView.as_view(),            name="auth-me"),
    path("register/", RegisterWard.as_view(), name="auth-register"),
]