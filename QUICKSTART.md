# Quick Start Guide - CUCM Live Monitor

## Prerequisites
- Docker and Docker Compose installed
- Network access to CUCM (port 8443)
- CUCM application user with API access

## Setup and Run

1. **Clone or download the repository**

2. **Create configuration file**:
```bash
cp .env.sample .env
```

3. **Edit `.env` with your CUCM credentials**:
```bash
nano .env
# or
vi .env
```

Update these values:
```
CUCM_HOST=your-cucm-hostname.example.com
CUCM_USERNAME=your_username
CUCM_PASSWORD=your_password
```

4. **Start the application**:
```bash
docker-compose up -d
```

5. **View logs** (optional):
```bash
docker-compose logs -f
```

6. **Access the dashboard**:
```
http://localhost:8000
```

7. **Configure via web interface** (alternative to .env):
   - Click the **⚙️ Settings** button in the dashboard
   - Enter your CUCM credentials
   - Save settings

8. **Stop the application**:
```bash
docker-compose down
```

## Troubleshooting

### Connection Timeout

**Error**: `Connection to cucm.example.com timed out`

**Possible causes**:
1. CUCM is not reachable from your network
2. Port 8443 is blocked by firewall
3. CUCM RIS service is not running

**Solutions**:
```bash
# Replace cucm.example.com with your actual CUCM hostname/IP

# Test network connectivity
ping cucm.example.com

# Test port 8443
telnet cucm.example.com 8443
# OR
nc -zv cucm.example.com 8443

# Test HTTPS access
curl -k https://cucm.example.com:8443/realtimeservice2/services/RISService?wsdl
```

### Authentication Errors

**Error**: `Authentication failed` or `401 Unauthorized`

**Solutions**:
1. Verify credentials in `.env` file
2. Ensure user has "Standard AXL API Access" role
3. Test credentials with CUCM admin page

### SSL Certificate Errors

The application disables SSL verification for self-signed certificates. This is normal for CUCM environments.

### Viewing Logs

**Docker**:
```bash
docker-compose logs -f cucm-monitor
```

Increase log verbosity by editing `.env`:
```bash
LOG_LEVEL=DEBUG
```

Then restart:
```bash
docker-compose restart
```

## Next Steps

For more detailed information, see:
- **README.md** - Complete documentation, API details, troubleshooting
- **Settings page** - Web-based configuration at http://localhost:8000/settings
- **Docker logs** - Real-time monitoring: `docker-compose logs -f`
