# CUCM Live Monitor

Real-time monitoring dashboard for Cisco Unified Communications Manager (CUCM) that displays active calls and registered devices.

## Features

- **Real-time Monitoring**: Live updates every 5 seconds via WebSocket
- **Active Call Tracking**: Total active calls across the CUCM cluster using PerfMon API
- **Individual Phone Call Status**: Real-time monitoring of each phone's call state (On Call/Idle)
- **Device Registration**: View all registered phones and endpoints with detailed information
- **Node Health Monitoring**: Visual indicators showing CUCM cluster node health
- **Web-based Configuration**: Easy setup through browser interface
- **Docker Deployment**: Portable containerized application
- **Clean UI**: Simple, responsive dashboard with real-time updates

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Network access to CUCM server
- CUCM application user with appropriate permissions

### Installation

1. **Clone or download this project**

2. **Configure CUCM credentials** (first-time setup)

   Copy the sample environment file and edit it:
   ```bash
   cp .env.sample .env
   ```

   Edit `.env` with your CUCM details:
   ```bash
   CUCM_HOST=cucm.example.com
   CUCM_USERNAME=your_cucm_username
   CUCM_PASSWORD=YourSecurePassword
   POLL_INTERVAL=5
   LOG_LEVEL=INFO
   ```

3. **Start the application**

   ```bash
   docker-compose up -d
   ```

4. **Access the dashboard**

   Open your browser to: `http://localhost:8000`

5. **Configure via web interface**

   Click the **⚙️ Settings** button in the dashboard to update credentials anytime.

## How It Works

This application uses two Cisco CUCM APIs to collect real-time information:

### 1. RIS API (Real-time Information Server)

**Purpose**: Get device registration status

The RIS API provides real-time device information including:
- Device names and IP addresses
- Registration status
- Device models
- Associated directory numbers

**Endpoint**: `https://{CUCM}:8443/realtimeservice2/services/RISService`

**WSDL**: `https://{CUCM}:8443/realtimeservice2/services/RISService?wsdl`

**Method Used**: `selectCmDevice`

**What We Get**:
- Total devices found
- Device registration status per CUCM node
- Device details (name, IP, description, model)
- List of CUCM nodes in the cluster

### 2. PerfMon API (Performance Monitoring)

**Purpose**: Get active call count across the CUCM cluster

The PerfMon API provides performance counters including real-time call statistics.

**Endpoint**: `https://{CUCM}:8443/perfmonservice2/services/PerfmonService`

**WSDL**: `https://{CUCM}:8443/perfmonservice2/services/PerfmonService?wsdl`

**Methods Used**:
1. `perfmonOpenSession` - Open a monitoring session
2. `perfmonAddCounter` - Add counters to monitor
3. `perfmonCollectSessionData` - Collect current counter values
4. `perfmonCloseSession` - Close the session

**Counters Used**:
- `\\{NodeName}\Cisco CallManager\CallsActive` - Active calls per node

**What We Get**:
- Real-time active call count per CUCM node
- Cluster-wide total active calls

### 3. Node Health Monitoring

**Purpose**: Monitor connectivity to all CUCM cluster nodes

The dashboard displays cluster node status using ICMP ping checks:
- **🟢 Green indicator**: Node is reachable (responds to ping)
- **🔴 Red indicator**: Node is unreachable (no ping response)

This approach checks basic network connectivity to all node types (Publisher, Subscribers, TFTP servers) regardless of which CUCM services are running on each node.

### 4. Phone Call Status Monitoring

**Purpose**: Monitor individual phone call status in real-time

The application polls each phone's web interface to determine if it's actively on a call:

**Endpoint**: `http://{phone_ip}/CGI/Java/Serviceability?adapter=device.statistics.streaming.0`

**Status Detection**:
- **🔴 On Call**: Phone streaming status shows `<b>Active</b>`
- **🟢 Idle**: Phone streaming status shows `<b>Not ready</b>`
- **⚪ Unknown**: Phone unreachable or status cannot be determined

**Polling**:
- Polls every 5 seconds for fast updates
- Parallel async requests for all phones
- 5-second timeout per phone to prevent blocking
- No authentication required (HTTP access to phone web interface)

### Rate Limiting Important!

PerfMon API has rate limiting:
- **Maximum**: 50 requests per minute
- **This app's solution**: Opens one session, adds all counters at once (CallsActive for each node), collects data, then closes
- With 5 nodes and 1 counter each, this is just 5 counters per poll, well within rate limits
- Efficient batching reduces API calls significantly while staying within limits

## API Endpoints

### Dashboard

- `GET /` - Main dashboard page
- `GET /settings` - Settings configuration page
- `GET /health` - Health check endpoint

### Data APIs

- `GET /api/status` - Get current cluster status (devices, calls)
- `GET /api/connection` - Get CUCM connection status
- `GET /api/settings` - Get current configuration (password masked)
- `POST /api/settings` - Update CUCM configuration
- `WebSocket /ws` - Real-time updates stream

## CUCM API Prerequisites

To use this application, you need to configure your CUCM server:

1. **Create Application User in CUCM**:
   - Navigate to: User Management > Application User
   - Create a new application user
   - Assign to "Standard CCM Admin Users" group (or similar role with API access)
   - Note the username and password for `.env` configuration

2. **Verify Required Services are Running**:
   - Navigate to: Cisco Unified Serviceability > Tools > Service Activation
   - Ensure these services are running:
     - **Cisco RIS Data Collector** (for device status)
     - **Cisco CallManager** (for PerfMon counters)

3. **Network Access**:
   - Ensure your Docker host or application server can reach CUCM on port 8443
   - CUCM uses self-signed certificates by default (application handles this)

## Troubleshooting

### Connection Issues

```bash
# Check logs
docker-compose logs -f cucm-monitor

# Test CUCM connectivity
curl -k https://cucm.example.com:8443/realtimeservice2/services/RISService?wsdl
```

### Rate Limiting Errors

If you see:
```
Exceeded allowed rate for Perfmon information
```

**Solution**: Increase `POLL_INTERVAL` in settings (default: 5 seconds, try 10)

### No Devices Showing

1. Verify user permissions in CUCM
2. Check that phones are registered to CUCM
3. Verify network connectivity from container to CUCM
4. Check logs for authentication errors

## Development

### Project Structure

```
CUCM_Live_Monitor/
├── app/
│   ├── main.py           # FastAPI application and API endpoints
│   ├── background.py     # Background polling tasks (RIS + phone status)
│   ├── ris_client.py     # RIS/PerfMon API client
│   ├── phone_poller.py   # Phone call status poller
│   ├── models.py         # Pydantic data models
│   └── config.py         # Configuration management
├── static/
│   ├── index.html        # Dashboard UI
│   ├── settings.html     # Settings configuration page
│   ├── app.js            # Frontend JavaScript (WebSocket, UI updates)
│   └── style.css         # Styling
├── Dockerfile            # Multi-stage Docker build
├── docker-compose.yml    # Docker Compose configuration
├── requirements.txt      # Python dependencies
├── .env.sample           # Sample environment configuration
├── .env                  # Your configuration (create from .env.sample)
├── .gitignore            # Git ignore patterns
├── README.md             # This file
├── QUICKSTART.md         # Quick start guide
└── LICENSE               # MIT License
```

## References

- [Cisco DevNet - RIS API](https://developer.cisco.com/docs/sxml/)
- [Cisco DevNet - PerfMon API](https://developer.cisco.com/docs/sxml/)
- [CUCM Administration Guide](https://www.cisco.com/c/en/us/support/unified-communications/unified-communications-manager-callmanager/products-maintenance-guides-list.html)

## License

MIT License - feel free to use and modify for your needs.
# CUCM-Live-Monitor
