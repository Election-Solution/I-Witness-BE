from django.shortcuts import render
from rest_framework import viewsets
from django.http import JsonResponse, HttpResponse

# Create your views here.
def index():
    return HttpResponse("Hello, World! This is the authentication app.")

# user report 

# The AI Triage

# Trigger a Django Signal or a WebSocket to notify the admin dashboard in real-time about the new report.

# send a success response back to the user confirming receipt of the report and providing an estimated response time.