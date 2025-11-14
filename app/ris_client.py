"""RIS (Real-time Information Server) API client for CUCM."""

import logging
import subprocess
from typing import List, Optional, Dict
from datetime import datetime
import requests
from zeep import Client, Settings, Transport
from zeep.exceptions import Fault
from requests.auth import HTTPBasicAuth
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from .models import DeviceStatus, ClusterStatus, NodeStatus
from .config import settings

# Disable SSL warnings for self-signed certificates
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)


class RISClient:
    """Client for CUCM RIS (Real-time Information Server) API."""

    def __init__(self):
        """Initialize RIS client."""
        self.cucm_host = settings.cucm_host
        self.username = settings.cucm_username
        self.password = settings.cucm_password
        # Use RISService for CUCM 12.5+
        self.wsdl_url = f"https://{self.cucm_host}:8443/realtimeservice2/services/RISService?wsdl"
        self.client: Optional[Client] = None
        self.connected = False
        self.last_error: Optional[str] = None
        self.last_successful_poll: Optional[datetime] = None

        # PerfMon client for active calls
        self.perfmon_client: Optional[Client] = None
        self.perfmon_connected = False
        self.cucm_nodes = []  # Will be populated from RIS query

    def connect(self) -> bool:
        """
        Establish connection to CUCM RIS service.

        Returns:
            bool: True if connection successful, False otherwise.
        """
        try:
            logger.info(f"Connecting to CUCM RIS service at {self.cucm_host}...")

            # Create session with authentication
            session = requests.Session()
            session.auth = HTTPBasicAuth(self.username, self.password)
            session.verify = False  # Disable SSL verification for self-signed certs

            # Configure Zeep transport
            transport = Transport(session=session, timeout=10)
            zeep_settings = Settings(strict=False, xml_huge_tree=True)

            # Create SOAP client
            self.client = Client(self.wsdl_url, transport=transport, settings=zeep_settings)

            # Override the service endpoint to use the correct CUCM host
            # (WSDL often contains localhost references)
            service_endpoint = f"https://{self.cucm_host}:8443/realtimeservice2/services/RISService"
            self.client.service._binding_options["address"] = service_endpoint

            # Skip test connection - will verify on first actual query
            # self._test_connection()

            self.connected = True
            self.last_error = None
            logger.info("Successfully connected to CUCM RIS service")
            return True

        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            logger.error(f"Failed to connect to CUCM RIS service: {e}")
            return False

    def _test_connection(self):
        """Test the RIS connection with a minimal query."""
        if not self.client:
            raise Exception("Client not initialized")

        # Create a minimal query to test connection
        criteria_factory = self.client.type_factory("ns0")

        # Create search criteria for devices
        # NodeName="": Empty string means all nodes
        # SelectItems: None means all items matching SelectBy
        criteria = criteria_factory.CmSelectionCriteria(
            MaxReturnedDevices=1,
            DeviceClass="Phone",
            Model=255,  # Any model
            Status="Any",
            NodeName="",
            SelectBy="Name",
            SelectItems=None,
        )

        state_info = ""

        # Execute query
        try:
            result = self.client.service.selectCmDevice(
                StateInfo=state_info, CmSelectionCriteria=criteria
            )
            logger.debug(f"Test connection successful: {result}")
        except Fault as fault:
            logger.error(f"SOAP Fault during test: {fault}")
            logger.error(f"Fault code: {fault.code if hasattr(fault, 'code') else 'N/A'}")
            logger.error(f"Fault message: {fault.message if hasattr(fault, 'message') else 'N/A'}")
            # Try to extract detail text
            if hasattr(fault, 'detail'):
                from lxml import etree
                detail_text = etree.tostring(fault.detail, encoding='unicode', pretty_print=True)
                logger.error(f"Fault detail XML:\n{detail_text}")
            raise

    def get_active_calls(self) -> Optional[ClusterStatus]:
        """
        Get current active call status from all devices.

        Returns:
            ClusterStatus: Current cluster status with device information.
        """
        if not self.connected or not self.client:
            logger.warning("Not connected to CUCM. Attempting to connect...")
            if not self.connect():
                return None

        try:
            logger.debug("Querying RIS for device status...")

            criteria_factory = self.client.type_factory("ns0")

            # Create search criteria - query all phone devices across ALL nodes
            # Try querying for specific device first, then expand to all
            select_items = criteria_factory.ArrayOfSelectItem()
            # Add specific device for testing
            select_item1 = criteria_factory.SelectItem(Item="SEPA0334FCEAE1A")
            # Add wildcard for all devices starting with SEP
            select_item2 = criteria_factory.SelectItem(Item="SEP*")
            select_items.item = [select_item1, select_item2]

            criteria = criteria_factory.CmSelectionCriteria(
                MaxReturnedDevices=1000,  # Adjust based on your environment
                DeviceClass="Phone",
                Model=255,  # Any model
                Status="Any",
                NodeName="",  # Empty = query ALL nodes (publisher + subscribers)
                SelectBy="Name",
                SelectItems=select_items,
            )

            state_info = ""

            # Execute RIS query
            result = self.client.service.selectCmDevice(
                StateInfo=state_info, CmSelectionCriteria=criteria
            )

            # Debug: Log the raw result structure
            logger.info(f"RIS Query Result: {result}")
            if hasattr(result, "SelectCmDeviceResult"):
                logger.info(f"SelectCmDeviceResult exists: {result.SelectCmDeviceResult}")
                if result.SelectCmDeviceResult and hasattr(result.SelectCmDeviceResult, "CmNodes"):
                    logger.info(f"CmNodes: {result.SelectCmDeviceResult.CmNodes}")

            # Parse the results
            devices = []
            total_calls = 0
            registered_count = 0
            nodes = []

            # Extract CUCM node names for PerfMon queries
            node_names = []

            if hasattr(result, "SelectCmDeviceResult") and result.SelectCmDeviceResult:
                logger.debug("✅ SelectCmDeviceResult exists and is not None")
                cm_nodes = result.SelectCmDeviceResult.CmNodes

                # The actual list of nodes is in CmNodes.CmNode, not CmNodes itself
                if hasattr(cm_nodes, 'CmNode') and cm_nodes.CmNode:
                    cm_devices = cm_nodes.CmNode
                    logger.debug(f"Found {len(cm_devices)} CUCM nodes")

                    # Extract node hostnames and status for PerfMon and UI
                    for node in cm_devices:
                        if hasattr(node, 'Name') and node.Name:
                            node_names.append(node.Name)

                            # Extract node status (ReturnCode: Ok, NotFound, etc.)
                            # Note: If the node appears in RIS response, it's up and running
                            # "NotFound" just means no devices registered, not that node is down
                            node_return_code = node.ReturnCode if hasattr(node, 'ReturnCode') else 'Unknown'
                            is_healthy = True  # Node responded to RIS query = node is up

                            nodes.append(NodeStatus(
                                name=node.Name,
                                status=node_return_code,
                                is_healthy=is_healthy
                            ))

                            logger.debug(f"Found CUCM node: {node.Name} (Status: {node_return_code})")

                    for idx, node in enumerate(cm_devices):
                        logger.debug(f"Processing node {idx}: {node.Name if hasattr(node, 'Name') else 'Unknown'}")

                        if hasattr(node, "CmDevices") and node.CmDevices:
                            # Access the actual device list from CmDevices.CmDevice
                            if hasattr(node.CmDevices, 'CmDevice') and node.CmDevices.CmDevice:
                                devices_list = node.CmDevices.CmDevice
                                logger.debug(f"✅ Node {idx} ({node.Name}) has {len(devices_list)} devices")
                                for dev_idx, device in enumerate(devices_list):
                                    # Debug: Log all available attributes for the first device to understand structure
                                    if dev_idx == 0:
                                        logger.info(f"Device attributes: {dir(device)}")
                                        # Log specific fields that might indicate call status
                                        for attr in ['Status', 'DeviceStatus', 'LineStatus', 'StreamingStatus',
                                                     'CallStatus', 'ActiveCalls', 'State', 'Ready']:
                                            if hasattr(device, attr):
                                                logger.info(f"Device.{attr}: {getattr(device, attr)}")

                                    # Extract device information
                                    device_name = device.Name if hasattr(device, "Name") else "Unknown"
                                    ip_address = (
                                        device.IpAddress if hasattr(device, "IpAddress") else None
                                    )
                                    status_str = (
                                        device.Status if hasattr(device, "Status") else "Unknown"
                                    )
                                    description = (
                                        device.Description
                                        if hasattr(device, "Description")
                                        else None
                                    )
                                    model = str(device.Model) if hasattr(device, "Model") and device.Model else None

                                    # Count active calls from DirNumber field
                                    # DirNumber format: "1234-Registered" or "1234-Connected,5678-Registered"
                                    active_calls = 0
                                    if hasattr(device, "DirNumber") and device.DirNumber:
                                        dir_numbers = str(device.DirNumber).split(',')
                                        for dir_num in dir_numbers:
                                            if '-' in dir_num:
                                                status = dir_num.split('-')[-1].strip()
                                                # Active call statuses: Connected, CallInProgress, CallRemotelyHeld, CallConnected
                                                if status in ['Connected', 'CallInProgress', 'CallRemotelyHeld', 'CallConnected']:
                                                    active_calls += 1

                                    # Track registered devices
                                    if "Registered" in status_str:
                                        registered_count += 1

                                    total_calls += active_calls

                                    devices.append(
                                        DeviceStatus(
                                            name=device_name,
                                            ip_address=ip_address,
                                            status=status_str,
                                            active_calls=active_calls,
                                            description=description,
                                            model=model,
                                        )
                                    )
                        else:
                            logger.debug(f"Node {idx} has no devices")
                else:
                    logger.debug("No CmNode found in CmNodes")
            else:
                logger.debug("SelectCmDeviceResult not found or empty")

            logger.info(f"Parsing complete: {len(devices)} devices parsed")
            self.last_successful_poll = datetime.now()
            self.last_error = None

            # Store CUCM nodes for PerfMon queries
            if node_names:
                self.cucm_nodes = node_names
                logger.debug(f"Stored {len(node_names)} CUCM nodes for PerfMon")

            # Get PerfMon metrics (active calls)
            perfmon_data = self.get_perfmon_metrics()
            total_calls = perfmon_data['total_calls']
            node_metrics = perfmon_data['node_metrics']

            # Check node health via ping
            node_health_status = self.check_node_health_ping(node_names)

            # Update node health
            for node in nodes:
                # Update health based on ping response
                if node.name in node_health_status:
                    node.is_healthy = node_health_status[node.name]
                    logger.debug(f"Updated {node.name} health from ping: {node.is_healthy}")

            cluster_status = ClusterStatus(
                total_devices=len(devices),
                registered_devices=registered_count,
                total_active_calls=total_calls,
                devices=devices,
                nodes=nodes,
                timestamp=datetime.now(),
                cucm_host=self.cucm_host,
            )

            logger.info(
                f"Retrieved status: {len(devices)} devices, "
                f"{registered_count} registered, {total_calls} active calls (from PerfMon)"
            )

            return cluster_status

        except Fault as fault:
            self.last_error = f"SOAP Fault: {fault.message if hasattr(fault, 'message') else str(fault)}"
            logger.error(f"SOAP fault while querying devices: {fault}")
            logger.error(f"Fault code: {fault.code if hasattr(fault, 'code') else 'N/A'}")
            logger.error(f"Fault detail: {fault.detail if hasattr(fault, 'detail') else 'N/A'}")
            self.connected = False
            return None
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error querying device status: {e}")
            self.connected = False
            return None

    def get_connection_status(self) -> dict:
        """
        Get current connection status.

        Returns:
            dict: Connection status information.
        """
        return {
            "connected": self.connected,
            "cucm_host": self.cucm_host,
            "last_error": self.last_error,
            "last_successful_poll": self.last_successful_poll.isoformat()
            if self.last_successful_poll
            else None,
        }

    def _connect_perfmon(self) -> bool:
        """
        Connect to CUCM PerfMon service.

        Returns:
            bool: True if connection successful, False otherwise.
        """
        if self.perfmon_connected and self.perfmon_client:
            return True

        try:
            logger.info("Connecting to CUCM PerfMon service...")

            perfmon_wsdl = f"https://{self.cucm_host}:8443/perfmonservice2/services/PerfmonService?wsdl"

            # Create session with authentication
            session = requests.Session()
            session.auth = HTTPBasicAuth(self.username, self.password)
            session.verify = False

            # Configure Zeep
            transport = Transport(session=session, timeout=10)
            zeep_settings = Settings(strict=False, xml_huge_tree=True)

            # Create SOAP client
            self.perfmon_client = Client(perfmon_wsdl, transport=transport, settings=zeep_settings)

            # Override endpoint
            service_endpoint = f"https://{self.cucm_host}:8443/perfmonservice2/services/PerfmonService"
            self.perfmon_client.service._binding_options["address"] = service_endpoint

            self.perfmon_connected = True
            logger.info("Successfully connected to CUCM PerfMon service")
            return True

        except Exception as e:
            self.perfmon_connected = False
            logger.error(f"Failed to connect to CUCM PerfMon service: {e}")
            return False

    def get_perfmon_metrics(self) -> dict:
        """
        Get PerfMon metrics (active calls) from all CUCM nodes.
        Uses a single session for all nodes to avoid rate limiting.

        Returns:
            dict: {
                'total_calls': int,
                'node_metrics': {
                    'hostname': {'calls': int},
                    ...
                }
            }
        """
        if not self.perfmon_connected:
            if not self._connect_perfmon():
                return {'total_calls': 0, 'node_metrics': {}}

        # If we don't have CUCM nodes yet, return empty metrics
        # Nodes will be populated from RIS query on first poll
        if not self.cucm_nodes:
            logger.debug("No CUCM nodes available yet for PerfMon metrics")
            return {'total_calls': 0, 'node_metrics': {}}

        try:
            type_factory = self.perfmon_client.type_factory("ns0")

            # Open ONE session for all nodes
            session_handle = self.perfmon_client.service.perfmonOpenSession()
            logger.debug(f"Opened PerfMon session: {session_handle}")

            try:
                # Create counters for ALL nodes (CallsActive only)
                counter_list = []

                for node_hostname in self.cucm_nodes:
                    # CallsActive counter
                    calls_counter_path = f"\\\\{node_hostname}\\Cisco CallManager\\CallsActive"
                    calls_counter = type_factory.CounterType()
                    calls_counter.Name = type_factory.CounterNameType(calls_counter_path)
                    counter_list.append(calls_counter)

                request_array = type_factory.RequestArrayOfCounterType()
                request_array.Counter = counter_list

                # Add counters
                self.perfmon_client.service.perfmonAddCounter(
                    SessionHandle=session_handle,
                    ArrayOfCounter=request_array
                )
                logger.debug("Successfully added CallsActive counters")

                # Collect data once for all nodes
                result = self.perfmon_client.service.perfmonCollectSessionData(
                    SessionHandle=session_handle
                )

                # Parse result - handle Zeep objects
                total_calls = 0
                node_metrics = {}

                if isinstance(result, list) and len(result) > 0:
                    for counter_info in result:
                        value = counter_info.Value if hasattr(counter_info, 'Value') else 0

                        # Extract node name from counter path
                        if hasattr(counter_info, 'Name') and hasattr(counter_info.Name, '_value_1'):
                            counter_name = counter_info.Name._value_1

                            # Parse counter name to get node hostname
                            # Format: \\hostname\Cisco CallManager\CallsActive
                            parts = counter_name.split('\\')
                            if len(parts) >= 4:
                                node_hostname = parts[2]

                                # Initialize node metrics if not exists
                                if node_hostname not in node_metrics:
                                    node_metrics[node_hostname] = {'calls': 0}

                                node_metrics[node_hostname]['calls'] = value
                                total_calls += value
                                logger.debug(f"Node {node_hostname}: {value} active calls")

                logger.info(f"PerfMon metrics - Total calls: {total_calls}, Nodes: {len(node_metrics)}")
                return {
                    'total_calls': total_calls,
                    'node_metrics': node_metrics
                }

            finally:
                # Always close the session
                try:
                    self.perfmon_client.service.perfmonCloseSession(SessionHandle=session_handle)
                    logger.debug("Closed PerfMon session")
                except Exception as e:
                    logger.warning(f"Error closing PerfMon session: {e}")

        except Exception as e:
            logger.error(f"Error getting PerfMon metrics: {e}")
            return {'total_calls': 0, 'node_metrics': {}}

    def check_node_health_ping(self, node_hostnames: List[str]) -> Dict[str, bool]:
        """
        Check node health by pinging each hostname.

        Args:
            node_hostnames: List of CUCM node hostnames to check

        Returns:
            Dict mapping hostname -> bool (True if pingable, False otherwise)
        """
        node_health = {}

        for hostname in node_hostnames:
            try:
                # Run ping command: -c 1 (1 packet), -W 2 (2 second timeout)
                result = subprocess.run(
                    ['ping', '-c', '1', '-W', '2', hostname],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3
                )

                # Exit code 0 = successful ping
                is_healthy = (result.returncode == 0)
                node_health[hostname] = is_healthy
                logger.debug(f"Ping check for {hostname}: {'Healthy' if is_healthy else 'Down'}")

            except subprocess.TimeoutExpired:
                node_health[hostname] = False
                logger.debug(f"Ping timeout for {hostname}: Down")
            except Exception as e:
                node_health[hostname] = False
                logger.warning(f"Ping check failed for {hostname}: {e}")

        return node_health
