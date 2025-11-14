"""Data models for CUCM Live Monitor."""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class DeviceStatus(BaseModel):
    """Device status information."""
    name: str
    ip_address: Optional[str] = None
    status: str  # "Registered", "Unregistered", "Unknown"
    active_calls: int = 0
    description: Optional[str] = None
    model: Optional[str] = None
    call_status: Optional[str] = None  # "On Call", "Idle", "Unknown"


class NodeStatus(BaseModel):
    """CUCM node status information."""
    name: str
    status: str  # "Ok", "NotFound", "Unknown"
    is_healthy: bool


class ClusterStatus(BaseModel):
    """Overall cluster status."""
    total_devices: int
    registered_devices: int
    total_active_calls: int
    devices: List[DeviceStatus]
    nodes: List[NodeStatus]
    timestamp: datetime
    cucm_host: str


class ConnectionStatus(BaseModel):
    """Connection status to CUCM."""
    connected: bool
    cucm_host: str
    error_message: Optional[str] = None
    last_successful_poll: Optional[datetime] = None
