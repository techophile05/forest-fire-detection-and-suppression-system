#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <SPI.h>
#include <LoRa.h>

// -------------------- WiFi Settings --------------------
const char* ssid = "Redmi Note 13 Pro 5G";
const char* password = "Passw@1234";

// -------------------- LoRa SX1278 Pins for ESP8266 --------------------
#define LORA_SCK 14   // GPIO14 (D5)
#define LORA_MISO 12  // GPIO12 (D6)  
#define LORA_MOSI 13  // GPIO13 (D7)
#define LORA_SS 15    // GPIO15 (D8)
#define LORA_RST 5    // GPIO5  (D1) - LoRa Reset
#define LORA_DIO0 4   // GPIO4  (D2) - LoRa DIO0
#define LORA_BAND 433E6

// -------------------- LED Status Indicators --------------------
#define STATUS_LED_PIN 0   // GPIO0 (D3) - LoRa data received indicator
#define WIFI_LED_PIN 2     // GPIO2 (D4) - WiFi/System status indicator

// -------------------- Web Server --------------------
ESP8266WebServer server(80);

struct SensorData {
  float temperature = 0.0;
  float humidity = 0.0;
  int smoke = 0;
  int gas = 0;
  bool isValid = false;
};

struct NodeData {
  String lastData;
  unsigned long lastSeen;
  SensorData sensors;
};
NodeData node;

// Flag for servo deploy
bool deployServo = false;

// -------------------- LED Control Variables --------------------
unsigned long lastDataLedBlink = 0;
unsigned long lastWifiLedBlink = 0;
int dataBlinkCount = 0;
bool dataLedState = false;
bool wifiLedState = false;
bool dataReceived = false;

// ==================== EMBEDDED WEB FILES ====================

const char* htmlPage = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="5">
    <title>🌲 Forest Fire Detection Dashboard</title>
    <link rel="stylesheet" href="style.css">
    <link rel="icon" type="image/png" href="favicon.png">
    <meta name="theme-color" content="#2d5016">
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="header">
            <div class="header-content">
                <div class="logo">
                    <span class="logo-icon">🌲</span>
                    <h1>Forest Fire Detection System</h1>
                </div>
                <nav class="nav">
                    <a href="#" class="nav-link active">Dashboard</a>
                    <a href="logs.html" class="nav-link">Logs</a>
                    <a href="settings.html" class="nav-link">Settings</a>
                    <a href="about.html" class="nav-link">About</a>
                </nav>
            </div>
        </header>
        :root {
            --bg: #0b1d10; --panel: #19351f; --accent: #2ecc71; --danger: #e74c3c;
            --text: #ecf0f1; --muted: #b8c6c9;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0; font-family: Arial, sans-serif;
            background: linear-gradient(135deg, var(--bg), #0e2414);
            color: var(--text); min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { color: var(--accent); margin: 0; }
        .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { background: var(--panel); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.1); }
        .card h3 { margin: 0 0 15px; color: var(--accent); }
        .sensor-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .sensor-card { background: var(--panel); border-radius: 10px; padding: 15px; text-align: center; }
        .sensor-value { font-size: 24px; font-weight: bold; color: var(--accent); margin: 10px 0; }
        .sensor-trend { font-size: 12px; color: var(--muted); }
        .btn-danger { background: var(--danger); color: white; border: none; padding: 15px 30px; border-radius: 8px; font-size: 16px; cursor: pointer; }
        .btn-danger:hover { background: #c0392b; }
        .raw-data { background: #000; color: #0f0; font-family: monospace; padding: 15px; border-radius: 8px; height: 200px; overflow-y: auto; margin-top: 20px; }
        .status-online { color: var(--accent); }
        .status-offline { color: var(--danger); }
        .alert-critical { background: rgba(231, 76, 60, 0.2); border: 1px solid var(--danger); }
        .alert-high { background: rgba(243, 156, 18, 0.2); border: 1px solid #f39c12; }
        .alert-normal { background: rgba(46, 204, 113, 0.2); border: 1px solid var(--accent); }
        @keyframes pulse { 0%, 100% { opacity: 0.7; } 50% { opacity: 1; } }
        .pulsing { animation: pulse 1s infinite; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌲 Forest Fire Detection System</h1>
            <p>Live ESP8266 Gateway - Real-time LoRa Data</p>
        </div>

        <!-- Main Content -->
        <main class="main">
            <!-- Status Cards -->
            <div class="status-grid">
                <div class="status-card system-status">
                    <div class="card-header">
                        <span class="card-icon">📡</span>
                        <h3>System Status</h3>
                    </div>
                    <div class="card-content">
                        <div class="status-indicator">
                            <span class="status-dot online" id="systemStatus"></span>
                            <span class="status-text" id="systemStatusText">System Online</span>
                        </div>
                        <div class="status-details">
                            <div class="detail-item">
                                <span class="detail-label">Gateway IP:</span>
                                <span class="detail-value" id="gatewayIP">Loading...</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">Uptime:</span>
                                <span class="detail-value" id="uptime">Loading...</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="status-card node-status">
                    <div class="card-header">
                        <span class="card-icon">🔗</span>
                        <h3>Node Status</h3>
                    </div>
                    <div class="card-content">
                        <div class="status-indicator">
                            <span class="status-dot" id="nodeStatus"></span>
                            <span class="status-text" id="nodeStatusText">Checking...</span>
                        </div>
                        <div class="status-details">
                            <div class="detail-item">
                                <span class="detail-label">Last Seen:</span>
                                <span class="detail-value" id="lastSeen">Never</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">Signal Strength:</span>
                                <span class="detail-value" id="signalStrength">-</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="status-card fire-alert">
                    <div class="card-header">
                        <span class="card-icon">🔥</span>
                        <h3>Fire Alert</h3>
                    </div>
                    <div class="card-content">
                        <div class="alert-level" id="alertLevel">
                            <span class="alert-text">No Alert</span>
                        </div>
                        <div class="status-details">
                            <div class="detail-item">
                                <span class="detail-label">Risk Level:</span>
                                <span class="detail-value" id="riskLevel">Low</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">Last Alert:</span>
                                <span class="detail-value" id="lastAlert">None</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sensor Data Section -->
            <div class="data-section">
                <div class="section-header">
                    <h2>📊 Live Sensor Data</h2>
                    <div class="refresh-indicator" id="refreshIndicator">
                        <span class="refresh-dot"></span>
                        <span>Auto-refresh: 3s</span>
                    </div>
                </div>

        <div class="sensor-grid">
            <div class="sensor-card">
                <h4>🌡️ Temperature</h4>
                <div class="sensor-value" id="temperature">--°C</div>
                <div class="sensor-trend" id="tempTrend">Loading...</div>
            </div>
            <div class="sensor-card">
                <h4>💧 Humidity</h4>
                <div class="sensor-value" id="humidity">--%</div>
                <div class="sensor-trend" id="humTrend">Loading...</div>
            </div>
            <div class="sensor-card">
                <h4>💨 Smoke Level</h4>
                <div class="sensor-value" id="smoke">-- ppm</div>
                <div class="sensor-trend" id="smokeTrend">Loading...</div>
            </div>
            <div class="sensor-card">
                <h4>⚠️ Gas Level</h4>
                <div class="sensor-value" id="gas">-- ppm</div>
                <div class="sensor-trend" id="gasTrend">Loading...</div>
            </div>
        </div>

        <div class="card">
            <h3>🎛️ Emergency Controls</h3>
            <form action="/deploy" method="POST" style="display: inline;">
                <button type="submit" class="btn-danger" onclick="return confirm('⚠️ Deploy Fire Extinguisher? This will send LoRa command to suppression systems!')">
                    🚨 Deploy Fire Extinguisher
                </button>
            </form>
            <p style="color: var(--muted); margin-top: 10px;">⚠️ This sends actual LoRa "DEPLOY" command to ESP32 nodes</p>
        </div>

        <div class="card">
            <h3>📋 Live LoRa Messages</h3>
            <div class="raw-data" id="rawData">Waiting for LoRa data from ESP32 nodes...</div>
        </div>
    </div>

    <script>
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
                this.fetchRealData(); // Connect to ESP8266 API
                this.setupEventListeners();
                
                // Update times every second
                setInterval(() => {
                    this.updateLastUpdateTime();
                    this.updateUptime();
                }, 1000);
            }
            
            fetchRealData() {
                setInterval(() => {
                    fetch('/api/data')
                .then(response => response.json())
                .then(data => {
                    // Update gateway info
                    document.getElementById('gatewayIP').textContent = data.gateway_ip || '10.118.178.118';
                    
                    // Update uptime
                    const uptimeSeconds = Math.floor(data.uptime / 1000);
                    const hours = Math.floor(uptimeSeconds / 3600);
                    const minutes = Math.floor((uptimeSeconds % 3600) / 60);
                    const seconds = uptimeSeconds % 60;
                    document.getElementById('uptime').textContent = 
                        `${hours.toString().padStart(2,'0')}:${minutes.toString().padStart(2,'0')}:${seconds.toString().padStart(2,'0')}`;
                    
                    // Update node status
                    const nodeOnline = data.node_online;
                    const nodeStatus = document.getElementById('nodeStatus');
                    if (nodeOnline) {
                        nodeStatus.innerHTML = '<span class="status-online">🟢 ESP32 ONLINE</span>';
                        document.getElementById('lastSeen').textContent = 'Just now';
                        document.getElementById('dataReceived').textContent = 'Live data';
                    } else {
                        nodeStatus.innerHTML = '<span class="status-offline">🔴 ESP32 OFFLINE</span>';
                        const timeDiff = Date.now() - data.last_seen;
                        const minutesAgo = Math.floor(timeDiff / 60000);
                        document.getElementById('lastSeen').textContent = minutesAgo > 0 ? `${minutesAgo} min ago` : 'Just now';
                    }
                    
                    // Update sensor data
                    if (data.sensors) {
                        const s = data.sensors;
                        document.getElementById('temperature').textContent = `${s.temperature}°C`;
                        document.getElementById('humidity').textContent = `${s.humidity}%`;
                        document.getElementById('smoke').textContent = `${s.smoke} ppm`;
                        document.getElementById('gas').textContent = `${s.gas} ppm`;
                        
                        // Update trends
                        document.getElementById('tempTrend').textContent = s.temperature > 35 ? 'High Risk' : s.temperature > 30 ? 'Elevated' : 'Normal';
                        document.getElementById('humTrend').textContent = s.humidity < 30 ? 'Fire Risk' : 'Normal';
                        document.getElementById('smokeTrend').textContent = s.smoke > 50 ? 'High' : 'Normal';
                        document.getElementById('gasTrend').textContent = s.gas > 100 ? 'High' : 'Normal';
                        
                        // Fire risk calculation
                        let riskScore = 0;
                        if (s.temperature > 35) riskScore += 40;
                        else if (s.temperature > 30) riskScore += 20;
                        if (s.humidity < 30) riskScore += 20;
                        if (s.smoke > 50) riskScore += 30;
                        if (s.gas > 100) riskScore += 10;
                        
                        const alertCard = document.getElementById('alertCard');
                        const alertLevel = document.getElementById('alertLevel');
                        const alertText = document.getElementById('alertText');
                        const riskLevel = document.getElementById('riskLevel');
                        
                        if (riskScore >= 60) {
                            alertLevel.className = 'alert-critical pulsing';
                            alertText.textContent = '🚨 CRITICAL ALERT';
                            riskLevel.textContent = 'Critical';
                        } else if (riskScore >= 30) {
                            alertLevel.className = 'alert-high';
                            alertText.textContent = '⚠️ HIGH ALERT';
                            riskLevel.textContent = 'High';
                        } else {
                            alertLevel.className = 'alert-normal';
                            alertText.textContent = '✅ No Alert';
                            riskLevel.textContent = 'Low';
                        }
                    }
                    
                    // Update raw data
                    if (data.last_data && data.last_data.length > 0) {
                        const rawData = document.getElementById('rawData');
                        const timestamp = new Date().toLocaleTimeString();
                        rawData.innerHTML = `[${timestamp}] Received: ${data.last_data}\n` + rawData.innerHTML;
                        // Keep only last 10 lines
                        const lines = rawData.innerHTML.split('\n').slice(0, 10);
                        rawData.innerHTML = lines.join('\n');
                    }
                })
                .catch(error => {
                    console.error('Error fetching data:', error);
                    document.getElementById('nodeStatus').innerHTML = '<span class="status-offline">🔴 CONNECTION ERROR</span>';
                });
        }
        
        // Update every 3 seconds
        setInterval(updateDashboard, 3000);
        updateDashboard(); // Initial load
    </script>
</body>
</html>
)rawliteral";

// ==================== CSS FILE ====================
const char* cssFile = R"rawliteral(
/* Forest Fire Detection System - Frontend Styles */
:root {
  --bg: #0b1d10;
  --bg2: #122818;
  --panel: #19351f;
  --accent: #2ecc71;
  --accent-2: #28a745;
  --warning: #f39c12;
  --danger: #e74c3c;
  --text: #ecf0f1;
  --muted: #b8c6c9;
  --link: #8fd3a9;
  --shadow: rgba(0,0,0,0.3);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", Arial, sans-serif;
  background: linear-gradient(135deg, var(--bg), #0e2414 40%, #0b1d10);
  color: var(--text);
  min-height: 100vh;
}

.container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(18, 40, 24, 0.8);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1100px;
  margin: 0 auto;
  padding: 14px 20px;
}

.logo { display: flex; align-items: center; gap: 10px; }
.logo-icon { font-size: 24px; }
.logo h1 { font-size: 18px; margin: 0; font-weight: 600; letter-spacing: 0.3px; }

.nav { display: flex; gap: 10px; }
.nav-link {
  color: var(--link);
  text-decoration: none;
  padding: 8px 12px;
  border-radius: 8px;
  transition: all 0.2s ease;
}
.nav-link:hover { background: rgba(255,255,255,0.07); }
.nav-link.active { background: rgba(46, 204, 113, 0.15); color: #baf3d0; }

.main { max-width: 1100px; margin: 20px auto; padding: 0 20px; flex: 1; }

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.status-card {
  background: var(--panel);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px;
  box-shadow: 0 10px 24px var(--shadow);
  overflow: hidden;
}

.card-header {
  display: flex; align-items: center; gap: 10px;
  padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,0.06);
  background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0));
}

.card-icon { font-size: 22px; }
.card-content { padding: 16px; }

.status-indicator { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; background: #888; box-shadow: 0 0 0 3px rgba(255,255,255,0.06) inset; }
.status-dot.online { background: var(--accent); }
.status-dot.offline { background: var(--danger); }
.status-text { font-weight: 600; color: #d9f7e6; }

.sensor-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.sensor-card { display: flex; align-items: center; gap: 12px; background: var(--panel); border: 1px solid rgba(255,255,255,0.06); padding: 14px; border-radius: 12px; }
.sensor-icon { font-size: 26px; }
.sensor-info h4 { margin: 0 0 6px; color: var(--muted); font-weight: 600; }
.sensor-value { font-size: 20px; font-weight: 700; }
.sensor-trend { color: var(--muted); font-size: 12px; }

.btn-danger, .btn-warning, .btn-secondary {
  border: none; cursor: pointer; padding: 10px 14px; border-radius: 10px; font-weight: 700; color: white; letter-spacing: 0.3px; transition: transform 0.05s ease, filter 0.2s ease;
}
.btn-danger { background: linear-gradient(180deg, #ff6b6b, #e74c3c); box-shadow: 0 6px 18px rgba(231, 76, 60, 0.4); }
.btn-warning { background: linear-gradient(180deg, #f7b731, #f39c12); box-shadow: 0 6px 18px rgba(243, 156, 18, 0.4); }
.btn-secondary { background: linear-gradient(180deg, #6c8e78, #557e64); box-shadow: 0 6px 18px rgba(85, 126, 100, 0.4); }
.btn-danger:hover, .btn-warning:hover, .btn-secondary:hover { filter: brightness(1.08); }

@media (max-width: 1000px) { .status-grid { grid-template-columns: 1fr 1fr; } .sensor-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 640px) {
  .status-grid { grid-template-columns: 1fr; }
  .sensor-grid { grid-template-columns: 1fr; }
  .header-content { flex-direction: column; gap: 10px; }
  .nav { width: 100%; justify-content: space-between; }
}
)rawliteral";

void handleRoot() {
  server.send(200, "text/html", htmlPage);
}

void handleCSS() {
  server.send(200, "text/css", cssFile);
}

void handleAPI() {
  String json = "{";
  json += "\"timestamp\":" + String(millis()) + ",";
  json += "\"node_online\":" + String((millis() - node.lastSeen < 15000) ? "true" : "false") + ",";
  json += "\"last_seen\":" + String(node.lastSeen) + ",";
  json += "\"gateway_ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"uptime\":" + String(millis()) + ",";
  
  if (node.sensors.isValid) {
    json += "\"sensors\":{";
    json += "\"temperature\":" + String(node.sensors.temperature, 1) + ",";
    json += "\"humidity\":" + String(node.sensors.humidity, 1) + ",";
    json += "\"smoke\":" + String(node.sensors.smoke) + ",";
    json += "\"gas\":" + String(node.sensors.gas);
    json += "},";
  } else {
    json += "\"sensors\":null,";
  }
  
  json += "\"last_data\":\"" + node.lastData + "\"";
  json += "}";
  
  server.send(200, "application/json", json);
}

void parseSensorData(String data) {
  // Expected format: "Temp:25.5,Hum:60.2,Smoke:45,Gas:23"
  int tempIndex = data.indexOf("Temp:");
  int humIndex = data.indexOf("Hum:");
  int smokeIndex = data.indexOf("Smoke:");
  int gasIndex = data.indexOf("Gas:");
  
  if (tempIndex != -1) {
    int commaIndex = data.indexOf(",", tempIndex);
    if (commaIndex != -1) {
      node.sensors.temperature = data.substring(tempIndex + 5, commaIndex).toFloat();
    }
  }
  
  if (humIndex != -1) {
    int commaIndex = data.indexOf(",", humIndex);
    if (commaIndex != -1) {
      node.sensors.humidity = data.substring(humIndex + 4, commaIndex).toFloat();
    }
  }
  
  if (smokeIndex != -1) {
    int commaIndex = data.indexOf(",", smokeIndex);
    if (commaIndex != -1) {
      node.sensors.smoke = data.substring(smokeIndex + 6, commaIndex).toInt();
    } else {
      node.sensors.smoke = data.substring(smokeIndex + 6).toInt();
    }
  }
  
  if (gasIndex != -1) {
    node.sensors.gas = data.substring(gasIndex + 4).toInt();
  }
  
  node.sensors.isValid = true;
}

void handleDeploy() {
  deployServo = true;
  server.sendHeader("Location", "/");
  server.send(303);
}

// ==================== LED CONTROL FUNCTIONS ====================

void initializeLEDs() {
  pinMode(STATUS_LED_PIN, OUTPUT);
  pinMode(WIFI_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);
  digitalWrite(WIFI_LED_PIN, LOW);
  Serial.println("LEDs initialized - D3 (Data) and D4 (WiFi)");
}

void startupLEDSequence() {
  Serial.println("Running LED startup sequence...");
  // Cool startup pattern - alternating blinks
  for (int i = 0; i < 6; i++) {
    digitalWrite(STATUS_LED_PIN, HIGH);
    digitalWrite(WIFI_LED_PIN, LOW);
    delay(150);
    digitalWrite(STATUS_LED_PIN, LOW);
    digitalWrite(WIFI_LED_PIN, HIGH);
    delay(150);
  }
  digitalWrite(WIFI_LED_PIN, LOW);
}

void triggerDataReceivedPattern() {
  dataReceived = true;
  dataBlinkCount = 0;
  lastDataLedBlink = millis();
  digitalWrite(STATUS_LED_PIN, HIGH);
  dataLedState = true;
}

void updateWiFiStatusLED() {
  unsigned long currentTime = millis();
  
  if (WiFi.status() == WL_CONNECTED) {
    // WiFi connected - slow breathing pattern (2 second cycle)
    if (currentTime - lastWifiLedBlink >= 1000) {
      wifiLedState = !wifiLedState;
      digitalWrite(WIFI_LED_PIN, wifiLedState);
      lastWifiLedBlink = currentTime;
    }
  } else {
    // WiFi disconnected - rapid blinking
    if (currentTime - lastWifiLedBlink >= 200) {
      wifiLedState = !wifiLedState;
      digitalWrite(WIFI_LED_PIN, wifiLedState);
      lastWifiLedBlink = currentTime;
    }
  }
}

void updateDataReceivedLED() {
  if (!dataReceived) return;
  
  unsigned long currentTime = millis();
  
  // Triple blink pattern when data is received
  if (dataBlinkCount < 6) { // 3 blinks = 6 state changes
    if (currentTime - lastDataLedBlink >= 100) {
      dataLedState = !dataLedState;
      digitalWrite(STATUS_LED_PIN, dataLedState);
      lastDataLedBlink = currentTime;
      dataBlinkCount++;
    }
  } else {
    // Finished blinking sequence
    dataReceived = false;
    digitalWrite(STATUS_LED_PIN, LOW);
    dataLedState = false;
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("ESP8266 LoRa Gateway Starting (No Plugin Version)...");

  // Initialize LEDs first
  initializeLEDs();
  startupLEDSequence();

  // WiFi Init
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    // Blink both LEDs rapidly while connecting
    digitalWrite(STATUS_LED_PIN, !digitalRead(STATUS_LED_PIN));
    digitalWrite(WIFI_LED_PIN, !digitalRead(WIFI_LED_PIN));
  }
  Serial.println("\nWiFi Connected! IP: " + WiFi.localIP().toString());
  
  // WiFi connected - turn on WiFi LED solid for 2 seconds
  digitalWrite(WIFI_LED_PIN, HIGH);
  digitalWrite(STATUS_LED_PIN, LOW);
  delay(2000);
  digitalWrite(WIFI_LED_PIN, LOW);

  // Web Server Init
  server.on("/", handleRoot);
  server.on("/style.css", handleCSS);
  server.on("/api/data", handleAPI);
  server.on("/deploy", HTTP_POST, handleDeploy);
  server.begin();
  Serial.println("Web Server Started - Dashboard embedded in code!");

  // LoRa Init
  SPI.begin();
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);
  if (!LoRa.begin(LORA_BAND)) {
    Serial.println("Starting LoRa failed!");
    while (1);
  }
  Serial.println("LoRa Gateway OK - Ready to receive from ESP32 nodes");
  Serial.println("Access dashboard at: http://" + WiFi.localIP().toString());
}

void loop() {
  server.handleClient();
  
  // Update LED patterns continuously
  updateWiFiStatusLED();
  updateDataReceivedLED();

  int packetSize = LoRa.parsePacket();
  if (packetSize) {
    String incoming = "";
    while (LoRa.available()) {
      incoming += (char)LoRa.read();
    }

    Serial.println("📡 Received from ESP32 node: " + incoming);
    node.lastSeen = millis();
    
    // Trigger LED pattern for any data received
    triggerDataReceivedPattern();

    if (incoming == "PING") {
      Serial.println("Ping received from ESP32 node.");
    } else {
      node.lastData = incoming;
      parseSensorData(incoming);
    }
  }

  if (deployServo) {
    LoRa.beginPacket();
    LoRa.print("DEPLOY");
    LoRa.endPacket();
    Serial.println("🚨 Deploy command sent to ESP32 nodes!");
    deployServo = false;
    
    // Special LED pattern for deploy command
    for (int i = 0; i < 10; i++) {
      digitalWrite(STATUS_LED_PIN, HIGH);
      digitalWrite(WIFI_LED_PIN, HIGH);
      delay(50);
      digitalWrite(STATUS_LED_PIN, LOW);
      digitalWrite(WIFI_LED_PIN, LOW);
      delay(50);
    }
  }
}
