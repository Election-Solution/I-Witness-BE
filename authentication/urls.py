from django.urls import path
from .views import *

# write your urls here.
urlpatterns = [
    path('', index, name='index'),
]
