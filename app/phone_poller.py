"""Phone streaming status poller."""

import asyncio
import logging
import re
from typing import Dict, Optional
import aiohttp

logger = logging.getLogger(__name__)


class PhonePoller:
    """Polls individual phone web interfaces to check call status."""

    def __init__(self):
        """Initialize phone poller."""
        self.call_status_cache: Dict[str, str] = {}  # {ip_address: "On Call" | "Idle" | "Unknown"}
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the phone polling task."""
        if self.running:
            logger.warning("Phone poller already running")
            return

        logger.info("Starting phone polling task (interval: 5s)")
        self.running = True
        self.task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        """Stop the phone polling task."""
        logger.info("Stopping phone poller")
        self.running = False

        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        """Main polling loop - runs every 60 seconds."""
        while self.running:
            try:
                # Poll phones will be triggered externally with the device list
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in phone polling loop: {e}")
                await asyncio.sleep(60)

    async def poll_phone(self, ip_address: str) -> str:
        """
        Poll a single phone's streaming status.

        Args:
            ip_address: Phone IP address.

        Returns:
            str: "On Call", "Idle", or "Unknown"
        """
        if not ip_address:
            return "Unknown"

        url = f"http://{ip_address}/CGI/Java/Serviceability?adapter=device.statistics.streaming.0"

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        html = await response.text()
                        return self._parse_stream_status(html)
                    else:
                        logger.debug(f"Phone {ip_address} returned status {response.status}")
                        return "Unknown"

        except asyncio.TimeoutError:
            logger.debug(f"Timeout polling phone {ip_address}")
            return "Unknown"
        except aiohttp.ClientError as e:
            logger.debug(f"HTTP error polling phone {ip_address}: {e}")
            return "Unknown"
        except Exception as e:
            logger.debug(f"Error polling phone {ip_address}: {e}")
            return "Unknown"

    def _parse_stream_status(self, html: str) -> str:
        """
        Parse HTML to extract stream status.

        Args:
            html: HTML response from phone.

        Returns:
            str: "On Call", "Idle", or "Unknown"
        """
        # Look for <b>Active</b> or <b>Not ready</b> or <b> Active</b> (with space)
        # Pattern: <b>Active</b> or <b> Active</b>
        active_pattern = re.compile(r'<b>\s*Active\s*</b>', re.IGNORECASE)
        not_ready_pattern = re.compile(r'<b>\s*Not ready\s*</b>', re.IGNORECASE)

        if active_pattern.search(html):
            return "On Call"
        elif not_ready_pattern.search(html):
            return "Idle"
        else:
            # Log first 500 chars for debugging if we can't parse
            logger.debug(f"Could not parse stream status. HTML snippet: {html[:500]}")
            return "Unknown"

    async def poll_all_phones(self, ip_addresses: list[str]) -> Dict[str, str]:
        """
        Poll all phones in parallel.

        Args:
            ip_addresses: List of phone IP addresses.

        Returns:
            Dict mapping IP address to call status.
        """
        if not ip_addresses:
            return {}

        logger.debug(f"Polling {len(ip_addresses)} phones...")

        # Poll all phones concurrently
        tasks = [self.poll_phone(ip) for ip in ip_addresses]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build result dict
        call_status_map = {}
        for ip, result in zip(ip_addresses, results):
            if isinstance(result, Exception):
                logger.debug(f"Exception polling {ip}: {result}")
                call_status_map[ip] = "Unknown"
            else:
                call_status_map[ip] = result

        # Update cache
        self.call_status_cache.update(call_status_map)

        logger.info(f"Phone polling complete: {len(call_status_map)} phones polled")
        return call_status_map

    def get_call_status(self, ip_address: str) -> str:
        """
        Get cached call status for a phone.

        Args:
            ip_address: Phone IP address.

        Returns:
            str: "On Call", "Idle", or "Unknown"
        """
        return self.call_status_cache.get(ip_address, "Unknown")
