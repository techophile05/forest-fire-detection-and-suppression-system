# 🌲 Forest Fire Detection System - Frontend

A modern, responsive web dashboard for the ESP32 LoRa Gateway Forest Fire Detection System. This frontend provides real-time monitoring, alerts, and control capabilities for early forest fire detection and automated suppression.

![Dashboard Preview](preview.png)

## ✨ Features

- **Real-time Monitoring**: Live sensor data display with auto-refresh
- **Fire Risk Analysis**: Intelligent risk scoring based on multiple sensor inputs
- **Alert System**: Visual and browser notifications for fire threats
- **Emergency Controls**: One-click fire suppression deployment
- **System Logs**: Comprehensive logging with filtering and export
- **Responsive Design**: Works on desktop, tablet, and mobile devices
- **PWA Ready**: Progressive Web App capabilities for mobile installation
- **Modern UI**: Dark forest theme with smooth animations

## 🚀 Quick Start

### Option 1: Use with ESP32 (Recommended)
1. Copy all files to your ESP32's web server directory
2. Update the ESP32 code to serve these files
3. Access via ESP32's IP address

### Option 2: Local Development
1. Extract all files to a local directory
2. Open `index.html` in a modern web browser
3. The demo will run with simulated data

## 📁 File Structure

```
forest-fire-frontend/
├── index.html          # Main dashboard
├── settings.html       # Configuration page
├── logs.html          # System logs viewer
├── about.html         # Project information
├── style.css          # Main stylesheet
├── script.js          # Dashboard functionality
├── manifest.json      # PWA manifest
└── README.md          # This file
```

## 🎛️ Dashboard Components

### Status Cards
- **System Status**: Gateway connectivity and uptime
- **Node Status**: LoRa sensor node connection status
- **Fire Alert**: Current risk level and alert status

### Live Sensor Data
- **Temperature**: Real-time temperature readings
- **Humidity**: Relative humidity monitoring
- **Smoke Level**: Smoke particle detection (ppm)
- **Gas Level**: Combustible gas detection (ppm)

### Emergency Controls
- **Fire Extinguisher**: Deploy suppression system
- **Alert System**: Manual alert testing and control

### Raw Data Display
- Real-time data stream from LoRa nodes
- Scrollable log with timestamps
- Clear function for data management

## ⚙️ Configuration

### ESP32 Integration
To integrate with your ESP32 LoRa Gateway:

1. **Copy files**: Place all frontend files in ESP32's SPIFFS/LittleFS
2. **Update ESP32 code**: Modify the `handleRoot()` function to serve `index.html`
3. **Data format**: Ensure LoRa data matches expected format: `"Temp:25.5,Hum:60.2,Smoke:45,Gas:23"`

### Data Format
The frontend expects sensor data in this format:
```
Temp:25.5,Hum:60.2,Smoke:45,Gas:23
```

### Alert Thresholds
Default thresholds can be configured in `settings.html`:
- Temperature: 35°C
- Humidity: 30% (low humidity alert)
- Smoke: 50 ppm
- Gas: 100 ppm

## 🔧 Customization

### Modifying Sensor Thresholds
Edit the threshold values in `script.js`:
```javascript
// Temperature risk thresholds
if (temp > 35) return 'High Risk';
if (temp > 30) return 'Elevated';

// Humidity risk thresholds  
if (hum < 30) return 'Fire Risk';
if (hum < 40) return 'Low Humidity';
```

### Changing Colors/Theme
Update CSS variables in `style.css`:
```css
:root {
  --bg: #0b1d10;      /* Background */
  --accent: #2ecc71;   /* Primary accent */
  --danger: #e74c3c;   /* Alert/danger */
  --warning: #f39c12;  /* Warning */
}
```

### Adding New Sensors
1. Add sensor card HTML in `index.html`
2. Add parsing logic in `updateSensorData()` function
3. Add threshold logic in appropriate trend functions

## 📱 Progressive Web App

The dashboard can be installed as a PWA:
1. Open the dashboard in Chrome/Edge
2. Click the install icon in the address bar
3. Confirm installation
4. Use like a native mobile app

## 🔄 Real-time Updates

The dashboard auto-refreshes every 5 seconds by default. To change:
1. Modify the meta refresh tag in HTML: `<meta http-equiv="refresh" content="5">`
2. Update JavaScript intervals in `script.js`

## 🚨 Fire Risk Calculation

The system calculates fire risk using a weighted scoring system:
- **Temperature**: 0-40 points (higher = more risk)
- **Humidity**: 0-20 points (lower = more risk)  
- **Smoke**: 0-30 points (higher = more risk)
- **Gas**: 0-10 points (higher = more risk)

**Risk Levels**:
- 0-19: Low Risk (Green)
- 20-39: Moderate Risk (Yellow)
- 40-69: High Risk (Orange)
- 70+: Critical Risk (Red)

## 🎨 Browser Support

- **Chrome**: 60+
- **Firefox**: 55+
- **Safari**: 12+
- **Edge**: 79+

## 🔧 Development

### Modifying JavaScript
The main dashboard logic is in `script.js`. Key classes and functions:
- `ForestFireDashboard`: Main dashboard controller
- `updateSensorData()`: Processes sensor readings
- `updateFireRisk()`: Calculates and displays fire risk
- `triggerAlert()`: Handles alert notifications

### Adding New Pages
1. Create new HTML file based on existing structure
2. Update navigation links in all pages
3. Add corresponding CSS if needed

## 🐛 Troubleshooting

### Dashboard Not Loading
- Check ESP32 is connected to WiFi
- Verify ESP32 IP address is correct
- Ensure all files are uploaded to ESP32

### No Sensor Data
- Check LoRa connections and configuration
- Verify sensor nodes are powered and transmitting
- Check data format matches expected format

### Alerts Not Working
- Enable browser notifications when prompted
- Check alert thresholds in settings
- Verify sensor data is being received

## 📞 Support

For issues, questions, or contributions:
- Check the troubleshooting section above
- Review the ESP32 Arduino code for integration
- Open issues on the project repository

## 📄 License

This project is open source. Feel free to modify and distribute according to your needs.

## 🙏 Acknowledgments

- ESP32 Arduino Core community
- LoRa library by Sandeep Mistry
- Font icons and modern web standards
- Open source IoT community

---

**Version**: 1.2.3  
**Last Updated**: January 25, 2024  
**Compatible with**: ESP32 LoRa Gateway v1.0+