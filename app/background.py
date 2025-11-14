"""Background task for polling CUCM RIS service."""

import asyncio
import logging
from typing import Set
from datetime import datetime

from .ris_client import RISClient
from .phone_poller import PhonePoller
from .models import ClusterStatus

logger = logging.getLogger(__name__)


class BackgroundPoller:
    """Background task that polls CUCM RIS service and broadcasts updates."""

    def __init__(self, poll_interval: int = 5):
        """
        Initialize background poller.

        Args:
            poll_interval: Interval in seconds between polls.
        """
        self.poll_interval = poll_interval
        self.ris_client = RISClient()
        self.phone_poller = PhonePoller()
        self.current_status: ClusterStatus | None = None
        self.running = False
        self.task: asyncio.Task | None = None
        self.phone_task: asyncio.Task | None = None
        self.websocket_clients: Set = set()

    async def start(self):
        """Start the background polling task."""
        if self.running:
            logger.warning("Background poller already running")
            return

        logger.info(f"Starting background poller (interval: {self.poll_interval}s)")
        self.running = True

        # Connect to CUCM
        await asyncio.to_thread(self.ris_client.connect)

        # Start polling loops
        self.task = asyncio.create_task(self._poll_loop())
        self.phone_task = asyncio.create_task(self._phone_poll_loop())

    async def stop(self):
        """Stop the background polling task."""
        logger.info("Stopping background poller")
        self.running = False

        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        if self.phone_task:
            self.phone_task.cancel()
            try:
                await self.phone_task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                # Poll RIS service
                logger.debug("Polling CUCM RIS service...")
                status = await asyncio.to_thread(self.ris_client.get_active_calls)

                if status:
                    # Merge phone call status into device status
                    for device in status.devices:
                        if device.ip_address:
                            device.call_status = self.phone_poller.get_call_status(device.ip_address)
                        else:
                            device.call_status = "Unknown"

                    self.current_status = status
                    # Broadcast to all connected WebSocket clients
                    await self._broadcast_update(status)
                else:
                    logger.warning("Failed to get status from CUCM")

            except Exception as e:
                logger.error(f"Error in polling loop: {e}")

            # Wait for next poll interval
            await asyncio.sleep(self.poll_interval)

    async def _phone_poll_loop(self):
        """Phone polling loop - runs every 5 seconds."""
        while self.running:
            try:
                # Get current device list with IP addresses
                if self.current_status and self.current_status.devices:
                    ip_addresses = [
                        device.ip_address
                        for device in self.current_status.devices
                        if device.ip_address
                    ]

                    if ip_addresses:
                        logger.debug(f"Polling {len(ip_addresses)} phones for call status...")
                        await self.phone_poller.poll_all_phones(ip_addresses)
                    else:
                        logger.debug("No phone IP addresses available for polling")
                else:
                    logger.debug("No device status available yet for phone polling")

            except Exception as e:
                logger.error(f"Error in phone polling loop: {e}")

            # Wait 5 seconds before next poll
            await asyncio.sleep(5)

    async def _broadcast_update(self, status: ClusterStatus):
        """
        Broadcast status update to all connected WebSocket clients.

        Args:
            status: Current cluster status to broadcast.
        """
        if not self.websocket_clients:
            return

        # Prepare message
        message = status.model_dump_json()

        # Send to all connected clients
        disconnected_clients = set()
        for websocket in self.websocket_clients:
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.debug(f"Failed to send to client: {e}")
                disconnected_clients.add(websocket)

        # Remove disconnected clients
        self.websocket_clients -= disconnected_clients

    def add_websocket_client(self, websocket):
        """Add a WebSocket client to receive updates."""
        self.websocket_clients.add(websocket)
        logger.info(f"WebSocket client added (total: {len(self.websocket_clients)})")

    def remove_websocket_client(self, websocket):
        """Remove a WebSocket client."""
        self.websocket_clients.discard(websocket)
        logger.info(f"WebSocket client removed (total: {len(self.websocket_clients)})")

    def get_current_status(self) -> ClusterStatus | None:
        """Get the most recent status."""
        return self.current_status

    def get_connection_status(self) -> dict:
        """Get connection status."""
        return self.ris_client.get_connection_status()
