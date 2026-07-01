// Forest Fire Detection System - Frontend JavaScript
class ForestFireDashboard {
    constructor() {
        this.lastDataTime = 0;
        this.sensorData = {};
        this.rawDataLines = [];
        this.maxRawDataLines = 100;
        this.startTime = Date.now();
        
        this.init();
    }

    init() {
        this.updateLastUpdateTime();
        this.simulateData(); // Remove this when connecting to real ESP32
        this.setupEventListeners();
        
        // Update times every second
        setInterval(() => {
            this.updateLastUpdateTime();
            this.updateUptime();
        }, 1000);
    }

    setupEventListeners() {
        // Deploy button confirmation
        const deployForm = document.querySelector('.deploy-form');
        if (deployForm) {
            deployForm.addEventListener('submit', (e) => {
                if (!confirm('⚠️ Are you sure you want to deploy the fire extinguisher? This action cannot be undone.')) {
                    e.preventDefault();
                }
            });
        }
    }

    updateLastUpdateTime() {
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        const dateString = now.toLocaleDateString();
        document.getElementById('lastUpdate').textContent = `${dateString} ${timeString}`;
    }

    updateUptime() {
        const uptimeMs = Date.now() - this.startTime;
        const uptimeSeconds = Math.floor(uptimeMs / 1000);
        const hours = Math.floor(uptimeSeconds / 3600);
        const minutes = Math.floor((uptimeSeconds % 3600) / 60);
        const seconds = uptimeSeconds % 60;
        
        document.getElementById('uptime').textContent = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    updateNodeStatus(isOnline, lastSeen = null) {
        const statusDot = document.getElementById('nodeStatus');
        const statusText = document.getElementById('nodeStatusText');
        const lastSeenElement = document.getElementById('lastSeen');
        
        if (isOnline) {
            statusDot.className = 'status-dot online';
            statusText.textContent = '🟢 ONLINE';
            lastSeenElement.textContent = 'Just now';
            this.lastDataTime = Date.now();
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = '🔴 OFFLINE';
            const timeDiff = Date.now() - this.lastDataTime;
            const minutesAgo = Math.floor(timeDiff / 60000);
            lastSeenElement.textContent = minutesAgo > 0 ? `${minutesAgo} min ago` : 'Just now';
        }
    }

    updateSensorData(data) {
        // Parse sensor data from ESP32 format
        // Expected format: "Temp:25.5,Hum:60.2,Smoke:45,Gas:23"
        if (typeof data === 'string') {
            const pairs = data.split(',');
            const parsed = {};
            
            pairs.forEach(pair => {
                const [key, value] = pair.split(':');
                if (key && value) {
                    parsed[key.toLowerCase().trim()] = parseFloat(value);
                }
            });
            
            this.sensorData = parsed;
        } else {
            this.sensorData = data;
        }
        
        this.updateSensorDisplay();
        this.updateFireRisk();
    }

    updateSensorDisplay() {
        const { temp, hum, smoke, gas } = this.sensorData;
        
        // Temperature
        if (temp !== undefined) {
            document.getElementById('temperature').textContent = `${temp}°C`;
            document.getElementById('tempTrend').textContent = this.getTempTrend(temp);
            document.getElementById('tempTrend').className = `sensor-trend ${this.getTempTrendClass(temp)}`;
        }
        
        // Humidity
        if (hum !== undefined) {
            document.getElementById('humidity').textContent = `${hum}%`;
            document.getElementById('humTrend').textContent = this.getHumTrend(hum);
            document.getElementById('humTrend').className = `sensor-trend ${this.getHumTrendClass(hum)}`;
        }
        
        // Smoke
        if (smoke !== undefined) {
            document.getElementById('smoke').textContent = `${smoke} ppm`;
            document.getElementById('smokeTrend').textContent = this.getSmokeTrend(smoke);
            document.getElementById('smokeTrend').className = `sensor-trend ${this.getSmokeTrendClass(smoke)}`;
        }
        
        // Gas
        if (gas !== undefined) {
            document.getElementById('gas').textContent = `${gas} ppm`;
            document.getElementById('gasTrend').textContent = this.getGasTrend(gas);
            document.getElementById('gasTrend').className = `sensor-trend ${this.getGasTrendClass(gas)}`;
        }
    }

    getTempTrend(temp) {
        if (temp > 35) return 'High Risk';
        if (temp > 30) return 'Elevated';
        if (temp > 25) return 'Normal';
        return 'Low';
    }

    getTempTrendClass(temp) {
        if (temp > 35) return 'danger';
        if (temp > 30) return 'warning';
        return 'normal';
    }

    getHumTrend(hum) {
        if (hum < 30) return 'Fire Risk';
        if (hum < 40) return 'Low Humidity';
        if (hum < 70) return 'Normal';
        return 'High';
    }

    getHumTrendClass(hum) {
        if (hum < 30) return 'danger';
        if (hum < 40) return 'warning';
        return 'normal';
    }

    getSmokeTrend(smoke) {
        if (smoke > 100) return 'Critical';
        if (smoke > 50) return 'High';
        if (smoke > 20) return 'Moderate';
        return 'Normal';
    }

    getSmokeTrendClass(smoke) {
        if (smoke > 100) return 'danger';
        if (smoke > 50) return 'warning';
        return 'normal';
    }

    getGasTrend(gas) {
        if (gas > 200) return 'Critical';
        if (gas > 100) return 'High';
        if (gas > 50) return 'Moderate';
        return 'Normal';
    }

    getGasTrendClass(gas) {
        if (gas > 200) return 'danger';
        if (gas > 100) return 'warning';
        return 'normal';
    }

    updateFireRisk() {
        const { temp = 0, hum = 100, smoke = 0, gas = 0 } = this.sensorData;
        
        let riskScore = 0;
        
        // Temperature risk (0-40 points)
        if (temp > 35) riskScore += 40;
        else if (temp > 30) riskScore += 25;
        else if (temp > 25) riskScore += 10;
        
        // Humidity risk (0-20 points, inverse relationship)
        if (hum < 30) riskScore += 20;
        else if (hum < 40) riskScore += 10;
        else if (hum < 50) riskScore += 5;
        
        // Smoke risk (0-30 points)
        if (smoke > 100) riskScore += 30;
        else if (smoke > 50) riskScore += 20;
        else if (smoke > 20) riskScore += 10;
        
        // Gas risk (0-10 points)
        if (gas > 200) riskScore += 10;
        else if (gas > 100) riskScore += 5;
        
        this.updateAlertDisplay(riskScore);
    }

    updateAlertDisplay(riskScore) {
        const alertLevel = document.getElementById('alertLevel');
        const alertText = alertLevel.querySelector('.alert-text');
        const riskLevelElement = document.getElementById('riskLevel');
        
        if (riskScore >= 70) {
            alertText.textContent = '🚨 CRITICAL ALERT';
            alertLevel.className = 'alert-level critical';
            riskLevelElement.textContent = 'Critical';
            this.triggerAlert('critical');
        } else if (riskScore >= 40) {
            alertText.textContent = '⚠️ HIGH ALERT';
            alertLevel.className = 'alert-level high';
            riskLevelElement.textContent = 'High';
            this.triggerAlert('high');
        } else if (riskScore >= 20) {
            alertText.textContent = '⚡ MODERATE ALERT';
            alertLevel.className = 'alert-level moderate';
            riskLevelElement.textContent = 'Moderate';
        } else {
            alertText.textContent = '✅ No Alert';
            alertLevel.className = 'alert-level normal';
            riskLevelElement.textContent = 'Low';
        }
    }

    triggerAlert(level) {
        // Update last alert time
        document.getElementById('lastAlert').textContent = new Date().toLocaleTimeString();
        
        // Flash the alert (visual feedback)
        const alertLevel = document.getElementById('alertLevel');
        alertLevel.style.animation = 'none';
        setTimeout(() => {
            alertLevel.style.animation = 'pulse 1s ease-in-out 3';
        }, 10);
        
        // You could add sound alerts, notifications, etc. here
        if (level === 'critical') {
            this.showNotification('🚨 CRITICAL FIRE ALERT! Immediate action required!');
        } else if (level === 'high') {
            this.showNotification('⚠️ High fire risk detected. Monitor closely.');
        }
    }

    showNotification(message) {
        // Browser notification (if permissions granted)
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Forest Fire Detection', {
                body: message,
                icon: 'favicon.png'
            });
        }
    }

    addRawDataLine(data) {
        const timestamp = new Date().toLocaleTimeString();
        this.rawDataLines.unshift(`[${timestamp}] ${data}`);
        
        // Keep only last N lines
        if (this.rawDataLines.length > this.maxRawDataLines) {
            this.rawDataLines = this.rawDataLines.slice(0, this.maxRawDataLines);
        }
        
        this.updateRawDataDisplay();
    }

    updateRawDataDisplay() {
        const rawDataElement = document.getElementById('rawData');
        
        if (this.rawDataLines.length === 0) {
            rawDataElement.innerHTML = '<div class="no-data">No data received yet...</div>';
        } else {
            const lines = this.rawDataLines.map(line => 
                `<div class="line">${this.escapeHtml(line)}</div>`
            ).join('');
            rawDataElement.innerHTML = lines;
        }
        
        // Auto-scroll to top for newest data
        rawDataElement.scrollTop = 0;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Simulate data for testing (remove when connecting to real ESP32)
    simulateData() {
        setInterval(() => {
            // Simulate sensor data
            const temp = 20 + Math.random() * 20;
            const hum = 40 + Math.random() * 40;
            const smoke = Math.random() * 80;
            const gas = Math.random() * 150;
            
            this.updateSensorData({ temp, hum, smoke, gas });
            this.updateNodeStatus(true);
            this.addRawDataLine(`Temp:${temp.toFixed(1)},Hum:${hum.toFixed(1)},Smoke:${smoke.toFixed(0)},Gas:${gas.toFixed(0)}`);
            
            // Simulate IP address
            document.getElementById('gatewayIP').textContent = '192.168.1.100';
        }, 2000);
    }
}

// Global functions for button actions
function clearRawData() {
    dashboard.rawDataLines = [];
    dashboard.updateRawDataDisplay();
}

function testAlert() {
    dashboard.showNotification('🔔 Test alert activated');
    alert('Test alert sent to monitoring systems.');
}

function silenceAlert() {
    alert('Alert system silenced for 10 minutes.');
}

// Request notification permissions on load
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
}

// Initialize dashboard when page loads
let dashboard;
document.addEventListener('DOMContentLoaded', () => {
    dashboard = new ForestFireDashboard();
});

// Add CSS classes for trends
const style = document.createElement('style');
style.textContent = `
    .sensor-trend.danger { color: #ff6b6b; }
    .sensor-trend.warning { color: #f39c12; }
    .sensor-trend.normal { color: #2ecc71; }
    .alert-level.critical { background: rgba(231, 76, 60, 0.2); border: 1px solid #e74c3c; }
    .alert-level.high { background: rgba(243, 156, 18, 0.2); border: 1px solid #f39c12; }
    .alert-level.moderate { background: rgba(241, 196, 15, 0.2); border: 1px solid #f1c40f; }
    .alert-level.normal { background: rgba(46, 204, 113, 0.2); border: 1px solid #2ecc71; }
`;
document.head.appendChild(style);