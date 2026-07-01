#!/usr/bin/env python3
"""
ESP8266 Data Scraper and Web Server
Scrapes sensor data from ESP8266 and hosts dashboard on local IP
"""

import requests
import re
import json
import time
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import threading
from datetime import datetime

# Configuration
ESP8266_IP = "10.118.178.118"
UPDATE_INTERVAL = 2  # seconds
LOCAL_PORT = 8080

# Global variables
latest_sensor_data = {
    "timestamp": None,
    "node_id": None,
    "temperature": None,
    "humidity": None,
    "gas": None,
    "flame": None,
    "fire_probability": None,
    "raw_message": None,
    "status": "waiting",
    "ai_fire_risk": None
}

# Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

class AdvancedFireRiskCalculator:
    def __init__(self):
        self.weights = {
            "temperature": 0.45,
            "humidity": 0.35,
            "gas": 0.20
        }
    
    def calculate_risk(self, temp, humidity, gas):
        """Calculate fire risk using only T, H, Gas (ignoring flame sensor)"""
        # Normalize risk factors
        temp_risk = 0.0 if temp <= 25 else 0.2 if temp <= 30 else 0.6 if temp <= 35 else 0.9
        humidity_risk = 0.0 if humidity >= 70 else 0.2 if humidity >= 50 else 0.6 if humidity >= 30 else 0.9
        gas_risk = 0.0 if gas <= 100 else 0.3 if gas <= 150 else 0.7 if gas <= 200 else 0.9
        
        # Calculate weighted risk
        risk_score = (
            temp_risk * self.weights["temperature"] +
            humidity_risk * self.weights["humidity"] +
            gas_risk * self.weights["gas"]
        ) * 100
        
        # Environmental correlations
        if temp > 32 and humidity < 30:
            risk_score *= 1.3
        if temp > 30 and gas > 180:
            risk_score *= 1.2
        if humidity < 20 and gas > 150:
            risk_score *= 1.15
            
        return min(100, max(0, risk_score))
    
    def get_risk_level(self, score):
        if score < 15:
            return "minimal"
        elif score < 35:
            return "low"
        elif score < 55:
            return "moderate"
        elif score < 75:
            return "high"
        else:
            return "critical"

fire_calculator = AdvancedFireRiskCalculator()

def scrape_esp8266_data():
    """Scrape sensor data from ESP8266"""
    global latest_sensor_data
    
    while True:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Scraping ESP8266...")
            
            # Fetch HTML from ESP8266
            response = requests.get(f"http://10.118.178.118//", timeout=5)
            html = response.text
            
            # Extract data using regex: <strong>Last Data:</strong><br>([^<]+)
            data_match = re.search(r'<strong>Last Data:</strong><br>([^<]+)', html)
            
            if data_match:
                raw_data = data_match.group(1).strip()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Raw data: {raw_data}")
                
                # Check if this is real sensor data (NODE pattern)
                sensor_pattern = r'NODE(\d+):T=([0-9.]+),H=([0-9.]+),MQ=([0-9.]+),F=([0-9.]+),FP=([0-9.]+)'
                sensor_match = re.match(sensor_pattern, raw_data)
                
                if sensor_match:
                    # Parse sensor data
                    node_id = f"NODE{sensor_match.group(1)}"
                    temperature = float(sensor_match.group(2))
                    humidity = float(sensor_match.group(3))
                    gas = int(sensor_match.group(4))
                    flame = int(sensor_match.group(5))
                    fire_probability = float(sensor_match.group(6))
                    
                    # Calculate our AI fire risk (ignoring flame sensor)
                    ai_risk = fire_calculator.calculate_risk(temperature, humidity, gas)
                    
                    # Update global data
                    latest_sensor_data = {
                        "timestamp": datetime.now().isoformat(),
                        "node_id": node_id,
                        "temperature": temperature,
                        "humidity": humidity,
                        "gas": gas,
                        "flame": flame,  # Keep for reference but don't use in UI
                        "fire_probability": fire_probability,  # ESP32's calculation (ignored)
                        "ai_fire_risk": round(ai_risk, 1),
                        "risk_level": fire_calculator.get_risk_level(ai_risk),
                        "raw_message": raw_data,
                        "status": "live_data"
                    }
                    
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ SENSOR DATA: T={temperature}°C, H={humidity}%, Gas={gas}ppm, AI Risk={ai_risk:.1f}%")
                    
                elif "ALIVE" in raw_data or "POLE" in raw_data:
                    # Heartbeat data
                    latest_sensor_data["raw_message"] = raw_data
                    latest_sensor_data["status"] = "heartbeat"
                    latest_sensor_data["timestamp"] = datetime.now().isoformat()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚪ Heartbeat: {raw_data}")
                    
                else:
                    # Unknown data
                    latest_sensor_data["raw_message"] = raw_data
                    latest_sensor_data["status"] = "unknown"
                    latest_sensor_data["timestamp"] = datetime.now().isoformat()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❓ Unknown: {raw_data}")
                    
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ No data found in HTML")
                latest_sensor_data["status"] = "no_data"
                
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ ESP8266 connection failed: {e}")
            latest_sensor_data["status"] = "connection_error"
            latest_sensor_data["timestamp"] = datetime.now().isoformat()
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Scraping error: {e}")
            latest_sensor_data["status"] = "error"
            
        time.sleep(UPDATE_INTERVAL)

# API Routes
@app.route('/api/data')
def get_sensor_data():
    """Return latest sensor data as JSON"""
    return jsonify(latest_sensor_data)

@app.route('/api/deploy', methods=['POST'])
def deploy_fire_suppression():
    """Deploy fire suppression systems"""
    try:
        response = requests.post(f"http://{ESP8266_IP}/deploy", timeout=5)
        if response.status_code in [200, 303]:
            return jsonify({"status": "success", "message": "Deploy command sent via LoRa"})
        else:
            return jsonify({"status": "error", "message": f"HTTP {response.status_code}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/')
def dashboard():
    """Serve the main dashboard"""
    dashboard_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌲 ForestGuard AI - Live Dashboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        :root {
            --bg-primary: #f8fafc;
            --bg-secondary: #ffffff;
            --accent-primary: #10b981;
            --accent-gradient: linear-gradient(135deg, #10b981 0%, #06d6a0 100%);
            --danger: #ef4444;
            --warning: #f59e0b;
            --text-primary: #1e293b;
            --text-secondary: #64748b;
            --border-light: #e2e8f0;
            --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            --radius-xl: 16px;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
        }

        .header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-light);
            padding: 1rem 2rem;
            box-shadow: var(--shadow-md);
            text-align: center;
        }

        .header h1 {
            font-size: 2rem;
            font-weight: 800;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.5rem;
        }

        .status-indicator {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 0.875rem;
        }

        .status-live {
            background: #ecfdf5;
            color: var(--accent-primary);
            border: 1px solid #bbf7d0;
        }

        .status-error {
            background: #fef2f2;
            color: var(--danger);
            border: 1px solid #fecaca;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        .alert-banner {
            padding: 1.5rem;
            border-radius: var(--radius-xl);
            text-align: center;
            margin-bottom: 2rem;
            background: linear-gradient(135deg, #ecfdf5, #d1fae5);
            border: 2px solid #bbf7d0;
            color: #065f46;
        }

        .alert-banner.warning {
            background: linear-gradient(135deg, #fffbeb, #fef3c7);
            border: 2px solid #fcd34d;
            color: #92400e;
        }

        .alert-banner.danger {
            background: linear-gradient(135deg, #fef2f2, #fee2e2);
            border: 2px solid #fca5a5;
            color: #991b1b;
        }

        .sensor-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .sensor-card {
            background: var(--bg-secondary);
            border-radius: var(--radius-xl);
            padding: 1.5rem;
            box-shadow: var(--shadow-md);
            border: 1px solid var(--border-light);
            text-align: center;
            transition: transform 0.3s ease;
        }

        .sensor-card:hover {
            transform: translateY(-4px);
        }

        .sensor-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
        }

        .sensor-value {
            font-size: 2.5rem;
            font-weight: 800;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.5rem;
        }

        .sensor-label {
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }

        .sensor-description {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }

        .deploy-btn {
            width: 100%;
            padding: 15px;
            font-size: 1.125rem;
            font-weight: 600;
            border: none;
            border-radius: var(--radius-xl);
            cursor: pointer;
            background: linear-gradient(135deg, var(--danger), #dc2626);
            color: white;
            transition: all 0.3s ease;
            margin: 1rem 0;
        }

        .deploy-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(239, 68, 68, 0.4);
        }

        .data-log {
            background: #1e293b;
            color: #10b981;
            padding: 1rem;
            border-radius: var(--radius-xl);
            font-family: monospace;
            font-size: 0.875rem;
            height: 200px;
            overflow-y: auto;
            margin-top: 1rem;
        }

        @media (max-width: 768px) {
            .sensor-grid { grid-template-columns: 1fr; }
            .container { padding: 1rem; }
        }
    </style>
</head>
<body>
    <header class="header">
        <h1>🌲 ForestGuard AI - Live Dashboard</h1>
        <div class="status-indicator" id="status">
            <div style="width: 8px; height: 8px; border-radius: 50%; background: #10b981;"></div>
            <span>Loading...</span>
        </div>
    </header>

    <div class="container">
        <div class="alert-banner" id="fireAlert">
            <h2 id="alertTitle">🔍 Monitoring Forest Conditions...</h2>
            <p id="alertDescription">Advanced AI fire risk analysis - Flame sensor ignored</p>
        </div>

        <div class="sensor-grid">
            <div class="sensor-card">
                <div class="sensor-icon">🌡️</div>
                <div class="sensor-value" id="tempValue">--</div>
                <div class="sensor-label">Temperature (°C)</div>
                <div class="sensor-description" id="tempDesc">Environmental temperature</div>
            </div>

            <div class="sensor-card">
                <div class="sensor-icon">💧</div>
                <div class="sensor-value" id="humValue">--</div>
                <div class="sensor-label">Humidity (%)</div>
                <div class="sensor-description" id="humDesc">Relative humidity</div>
            </div>

            <div class="sensor-card">
                <div class="sensor-icon">⚠️</div>
                <div class="sensor-value" id="gasValue">--</div>
                <div class="sensor-label">Gas Level (ppm)</div>
                <div class="sensor-description" id="gasDesc">Combustible gas concentration</div>
            </div>

            <div class="sensor-card">
                <div class="sensor-icon">🔥</div>
                <div class="sensor-value" id="riskValue">--</div>
                <div class="sensor-label">Fire Danger Level</div>
                <div class="sensor-description" id="riskDesc">Smart prediction system</div>
            </div>
        </div>

        <button class="deploy-btn" onclick="deployFireSuppression()">
            🧯 Deploy Fire Extinguisher Systems
        </button>

        <div class="data-log" id="dataLog">
            [SYSTEM] ForestGuard AI Dashboard initialized<br>
            [SYSTEM] Connecting to sensor data API...<br>
        </div>
    </div>

    <script>
        let lastUpdate = 0;
        
        async function fetchSensorData() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                
                updateDashboard(data);
                updateStatus('live');
                
            } catch (error) {
                console.error('Failed to fetch data:', error);
                updateStatus('error');
                addLog(`[ERROR] ${error.message}`);
            }
        }
        
        function updateDashboard(data) {
            if (data.status === 'live_data') {
                // Update sensor values
                document.getElementById('tempValue').textContent = data.temperature?.toFixed(1) || '--';
                document.getElementById('humValue').textContent = data.humidity?.toFixed(1) || '--';
                document.getElementById('gasValue').textContent = data.gas || '--';
                document.getElementById('riskValue').textContent = data.ai_fire_risk || '--';
                
                // Update descriptions
                document.getElementById('tempDesc').textContent = 
                    data.temperature > 30 ? 'Elevated - fire risk increased' : 'Normal conditions';
                document.getElementById('humDesc').textContent = 
                    data.humidity < 35 ? 'Low - increased fire risk' : 'Good fire prevention levels';
                document.getElementById('gasDesc').textContent = 
                    data.gas > 150 ? 'Elevated concentration' : 'Normal atmospheric levels';
                // Show user-friendly risk level descriptions
                const riskLabels = {
                    'minimal': 'Very Safe',
                    'low': 'Safe Conditions', 
                    'moderate': 'Caution Advised',
                    'high': 'High Alert',
                    'critical': 'Danger Zone'
                };
                document.getElementById('riskDesc').textContent = 
                    riskLabels[data.risk_level] || 'Calculating...';
                
                // Update fire alert
                updateFireAlert(data);
                
                if (Date.now() - lastUpdate > 5000) {
                    addLog(`[${new Date().toLocaleTimeString()}] Live: T=${data.temperature}°C, H=${data.humidity}%, Gas=${data.gas}ppm, Risk=${data.ai_fire_risk}%`);
                    lastUpdate = Date.now();
                }
                
            } else if (data.status === 'heartbeat') {
                addLog(`[${new Date().toLocaleTimeString()}] Heartbeat: ${data.raw_message}`);
            }
        }
        
        function updateFireAlert(data) {
            const alertEl = document.getElementById('fireAlert');
            const titleEl = document.getElementById('alertTitle');
            const descEl = document.getElementById('alertDescription');
            
            const risk = data.ai_fire_risk || 0;
            const level = data.risk_level || 'unknown';
            
            // User-friendly alert messages
            const alertMessages = {
                'minimal': { icon: '✅', title: 'Very Safe', desc: 'Excellent conditions - Forest is well protected' },
                'low': { icon: '✅', title: 'Safe Conditions', desc: 'Good environmental conditions - Normal monitoring' },
                'moderate': { icon: '⚡', title: 'Caution Advised', desc: 'Some risk factors detected - Keep watching conditions' },
                'high': { icon: '⚠️', title: 'High Alert', desc: 'Dangerous conditions developing - Consider preventive action' },
                'critical': { icon: '🚨', title: 'Danger Zone', desc: 'CRITICAL SITUATION - Fire suppression may be needed!' }
            };
            
            const message = alertMessages[level] || { icon: '🔍', title: 'Monitoring', desc: 'Analyzing conditions...' };
            
            if (risk < 35) {
                alertEl.className = 'alert-banner';
                titleEl.textContent = `${message.icon} ${message.title} (${risk}%)`;
                descEl.textContent = message.desc;
            } else if (risk < 75) {
                alertEl.className = 'alert-banner warning';
                titleEl.textContent = `${message.icon} ${message.title} (${risk}%)`;
                descEl.textContent = message.desc;
            } else {
                alertEl.className = 'alert-banner danger';
                titleEl.textContent = `${message.icon} ${message.title} (${risk}%)`;
                descEl.textContent = message.desc;
            }
        }
        
        function updateStatus(status) {
            const statusEl = document.getElementById('status');
            if (status === 'live') {
                statusEl.className = 'status-indicator status-live';
                statusEl.innerHTML = '<div style="width: 8px; height: 8px; border-radius: 50%; background: #10b981;"></div><span>Live Data</span>';
            } else {
                statusEl.className = 'status-indicator status-error';
                statusEl.innerHTML = '<div style="width: 8px; height: 8px; border-radius: 50%; background: #ef4444;"></div><span>Connection Error</span>';
            }
        }
        
        async function deployFireSuppression() {
            if (confirm('🚨 EMERGENCY DEPLOYMENT\\n\\nThis will send DEPLOY command via LoRa to all ESP32 sensor nodes.\\n\\nProceed?')) {
                addLog('[EMERGENCY] Fire suppression deployment initiated');
                try {
                    const response = await fetch('/api/deploy', { method: 'POST' });
                    const result = await response.json();
                    
                    if (result.status === 'success') {
                        addLog('[DEPLOY] ✅ Command sent via LoRa');
                        alert('🚨 Deployment Complete!\\n\\n✅ DEPLOY command sent\\n🧯 Fire extinguishers should activate now');
                    } else {
                        throw new Error(result.message);
                    }
                } catch (error) {
                    addLog(`[ERROR] Deployment failed: ${error.message}`);
                    alert(`❌ Deployment Error: ${error.message}`);
                }
            }
        }
        
        function addLog(message) {
            const logEl = document.getElementById('dataLog');
            logEl.innerHTML += message + '<br>';
            logEl.scrollTop = logEl.scrollHeight;
            
            const lines = logEl.innerHTML.split('<br>');
            if (lines.length > 50) {
                logEl.innerHTML = lines.slice(-50).join('<br>');
            }
        }
        
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            addLog('[SYSTEM] Dashboard initialized');
            addLog('[SYSTEM] Starting live data updates...');
            
            // Fetch data immediately and every 2 seconds
            fetchSensorData();
            setInterval(fetchSensorData, 2000);
        });
    </script>
</body>
</html>
    """
    return render_template_string(dashboard_html)

if __name__ == '__main__':
    print("🌲 ForestGuard AI - ESP8266 Data Scraper & Web Server")
    print("="*50)
    print(f"🔍 Scraping data from: http://{ESP8266_IP}/")
    print(f"🌐 Starting web server on: http://localhost:{LOCAL_PORT}/")
    print(f"⏱️  Update interval: {UPDATE_INTERVAL} seconds")
    print("="*50)
    
    # Start scraper thread
    scraper_thread = threading.Thread(target=scrape_esp8266_data, daemon=True)
    scraper_thread.start()
    
    # Start web server
    try:
        app.run(host='0.0.0.0', port=LOCAL_PORT, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")