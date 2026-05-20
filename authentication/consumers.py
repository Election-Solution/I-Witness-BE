import json
from channels.generic.websocket import AsyncWebsocketConsumer

class IncidentConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("incidents", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("incidents", self.channel_name)

    async def incident_update(self, event):
        """Receives from Celery via group_send, forwards to WebSocket client."""
        await self.send(text_data=json.dumps(event["data"]))