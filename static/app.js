// CUCM Live Monitor - Frontend Application

class CUCMMonitor {
    constructor() {
        this.ws = null;
        this.reconnectInterval = 3000;
        this.currentData = null;
        this.previousCallCount = 0;

        this.init();
    }

    init() {
        this.setupWebSocket();
        this.setupEventListeners();
        console.log('CUCM Monitor initialized');
    }

    setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        console.log('Connecting to WebSocket:', wsUrl);

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.updateConnectionStatus(true);
                this.hideError();
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleUpdate(data);
                } catch (error) {
                    console.error('Error parsing message:', error);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.updateConnectionStatus(false);
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.showError('Connection error. Retrying...');
            };

        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.updateConnectionStatus(false);
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        console.log(`Reconnecting in ${this.reconnectInterval / 1000} seconds...`);
        setTimeout(() => {
            this.setupWebSocket();
        }, this.reconnectInterval);
    }

    handleUpdate(data) {
        console.log('Received update:', data);
        this.currentData = data;

        // Update stats
        this.updateStats(data);

        // Update cluster nodes status
        this.updateNodesStatus(data.nodes);

        // Update devices table
        this.updateDevicesTable(data.devices);

        // Update timestamp
        this.updateTimestamp(data.timestamp);

        // Animate call count change
        if (this.previousCallCount !== data.total_active_calls) {
            this.animateCallCount(data.total_active_calls);
            this.previousCallCount = data.total_active_calls;
        }
    }

    updateStats(data) {
        // Registered devices
        document.getElementById('registered-devices').textContent = data.registered_devices || 0;

        // Active calls
        const callsElement = document.getElementById('active-calls');
        callsElement.textContent = data.total_active_calls || 0;

        // CUCM host
        document.getElementById('cucm-host').textContent = data.cucm_host || 'Unknown';
    }

    animateCallCount(newValue) {
        const element = document.getElementById('active-calls');
        element.classList.add('updating');
        setTimeout(() => {
            element.classList.remove('updating');
        }, 300);
    }

    updateNodesStatus(nodes) {
        const clusterNodesDiv = document.getElementById('cluster-nodes');
        const nodesContainer = document.getElementById('nodes-container');

        if (!nodes || nodes.length === 0) {
            clusterNodesDiv.style.display = 'none';
            return;
        }

        // Show the cluster nodes section
        clusterNodesDiv.style.display = 'flex';

        // Generate node badges
        nodesContainer.innerHTML = nodes.map(node => {
            const healthClass = node.is_healthy ? 'healthy' : 'unhealthy';
            const nodeName = this.formatNodeName(node.name);

            return `
                <div class="node-badge ${healthClass}" title="${this.escapeHtml(node.name)} - ${node.status}">
                    <div class="node-dot ${healthClass}"></div>
                    <span class="node-name">${this.escapeHtml(nodeName)}</span>
                </div>
            `;
        }).join('');
    }

    formatNodeName(fullName) {
        // Shorten node names for display (e.g., uat-clt-ucmpubc1.bbtnet.com -> ucmpubc1)
        const parts = fullName.split('.');
        if (parts.length > 0) {
            const hostname = parts[0];
            const nameParts = hostname.split('-');
            // Get the last meaningful part (e.g., ucmpubc1, ucmsub1c1)
            return nameParts[nameParts.length - 1] || hostname;
        }
        return fullName;
    }

    updateDevicesTable(devices) {
        const tbody = document.getElementById('devices-tbody');

        if (!devices || devices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="no-devices">No devices found</td></tr>';
            return;
        }

        // Sort by device name
        devices.sort((a, b) => a.name.localeCompare(b.name));

        // Generate table rows
        tbody.innerHTML = devices.map(device => {
            // Make IP address clickable if available
            const ipDisplay = device.ip_address
                ? `<a href="http://${device.ip_address}" target="_blank" class="device-ip-link" title="Open device web page">${device.ip_address}</a>`
                : 'N/A';

            // Get call status display
            const callStatusDisplay = this.getCallStatusDisplay(device.call_status);

            return `
                <tr>
                    <td><strong>${this.escapeHtml(device.name)}</strong></td>
                    <td>${this.escapeHtml(device.description || 'N/A')}</td>
                    <td>
                        <span class="device-status ${this.getStatusClass(device.status)}">
                            ${device.status}
                        </span>
                    </td>
                    <td>
                        <span class="call-status ${callStatusDisplay.className}">
                            ${callStatusDisplay.icon} ${callStatusDisplay.text}
                        </span>
                    </td>
                    <td>${ipDisplay}</td>
                </tr>
            `;
        }).join('');

        // Update device count
        document.getElementById('device-count').textContent =
            `${devices.length} device${devices.length !== 1 ? 's' : ''}`;
    }

    getStatusClass(status) {
        if (status.includes('Registered')) return 'registered';
        if (status.includes('Unregistered')) return 'unregistered';
        return 'unknown';
    }

    getCallStatusDisplay(callStatus) {
        // Call status: "On Call", "Idle", "Unknown"
        if (callStatus === 'On Call') {
            return { icon: '🔴', text: 'On Call', className: 'call-active' };
        } else if (callStatus === 'Idle') {
            return { icon: '🟢', text: 'Idle', className: 'call-idle' };
        } else {
            return { icon: '⚪', text: 'Unknown', className: 'call-unknown' };
        }
    }

    updateTimestamp(timestamp) {
        const date = new Date(timestamp);
        const formatted = date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
        document.getElementById('last-update').textContent = formatted;
    }

    updateConnectionStatus(connected) {
        const indicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('status-text');

        if (connected) {
            indicator.classList.remove('disconnected');
            indicator.classList.add('connected');
            statusText.textContent = 'Connected';
        } else {
            indicator.classList.remove('connected');
            indicator.classList.add('disconnected');
            statusText.textContent = 'Disconnected';
        }
    }

    showError(message) {
        const errorDiv = document.getElementById('error-message');
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }

    hideError() {
        const errorDiv = document.getElementById('error-message');
        errorDiv.style.display = 'none';
    }

    setupEventListeners() {
        // Periodic ping to keep connection alive
        setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send('ping');
            }
        }, 30000);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.monitor = new CUCMMonitor();
});
