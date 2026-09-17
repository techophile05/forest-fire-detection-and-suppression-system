#!/usr/bin/env python3
"""
Forest Fire Detection and Suppression System — backend.

Polls the ESP8266 LoRa gateway for real sensor data, computes fire risk,
optionally emails alerts, and exposes deploy only via POST /api/deploy.
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration (environment only — no secrets in source)
# ---------------------------------------------------------------------------

ESP_IP = os.getenv("ESP_IP", "10.152.162.188").strip()
ESP_PORT = int(os.getenv("ESP_PORT", "80"))
ESP_POLL_INTERVAL = float(os.getenv("ESP_POLL_INTERVAL", "2"))
ESP_TIMEOUT = float(os.getenv("ESP_TIMEOUT", "5"))
ESP_STALE_SECONDS = float(os.getenv("ESP_STALE_SECONDS", "15"))
ESP_DATA_PATH = os.getenv("ESP_DATA_PATH", "/api/data").strip() or "/api/data"
ESP_DEPLOY_PATH = os.getenv("ESP_DEPLOY_PATH", "/deploy").strip() or "/deploy"

FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "8080"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")

EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
ALERT_COOLDOWN_SECONDS = float(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
ALERT_MIN_LEVEL = os.getenv("ALERT_MIN_LEVEL", "high").strip().lower()

# Deterministic environmental risk thresholds / weights
RISK_TEMP_LOW = float(os.getenv("RISK_TEMP_LOW", "25"))
RISK_TEMP_MID = float(os.getenv("RISK_TEMP_MID", "30"))
RISK_TEMP_HIGH = float(os.getenv("RISK_TEMP_HIGH", "35"))
RISK_HUM_HIGH = float(os.getenv("RISK_HUM_HIGH", "70"))
RISK_HUM_MID = float(os.getenv("RISK_HUM_MID", "50"))
RISK_HUM_LOW = float(os.getenv("RISK_HUM_LOW", "30"))
RISK_GAS_LOW = float(os.getenv("RISK_GAS_LOW", "100"))
RISK_GAS_MID = float(os.getenv("RISK_GAS_MID", "150"))
RISK_GAS_HIGH = float(os.getenv("RISK_GAS_HIGH", "200"))
RISK_PRESSURE_LOW = float(os.getenv("RISK_PRESSURE_LOW", "1000"))
RISK_PRESSURE_MID = float(os.getenv("RISK_PRESSURE_MID", "1010"))
RISK_WEIGHT_TEMPERATURE = float(os.getenv("RISK_WEIGHT_TEMPERATURE", "0.40"))
RISK_WEIGHT_HUMIDITY = float(os.getenv("RISK_WEIGHT_HUMIDITY", "0.30"))
RISK_WEIGHT_GAS = float(os.getenv("RISK_WEIGHT_GAS", "0.25"))
RISK_WEIGHT_PRESSURE = float(os.getenv("RISK_WEIGHT_PRESSURE", "0.05"))
RISK_COMBO_TEMP_HUM_MULT = float(os.getenv("RISK_COMBO_TEMP_HUM_MULT", "1.3"))
RISK_COMBO_TEMP_GAS_MULT = float(os.getenv("RISK_COMBO_TEMP_GAS_MULT", "1.2"))
RISK_COMBO_HUM_GAS_MULT = float(os.getenv("RISK_COMBO_HUM_GAS_MULT", "1.15"))
RISK_LEVEL_LOW = float(os.getenv("RISK_LEVEL_LOW", "15"))
RISK_LEVEL_MODERATE = float(os.getenv("RISK_LEVEL_MODERATE", "35"))
RISK_LEVEL_HIGH = float(os.getenv("RISK_LEVEL_HIGH", "55"))
RISK_LEVEL_CRITICAL = float(os.getenv("RISK_LEVEL_CRITICAL", "75"))

# Random Forest
FIRE_CLASSES = ("None", "Potential Fire", "Confirmed Fire")
ML_DATASET_PATH = os.getenv("ML_DATASET_PATH", os.path.join("data", "fire_labels.csv"))
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", os.path.join("models", "fire_rf.joblib"))
ML_N_ESTIMATORS = int(os.getenv("ML_N_ESTIMATORS", "100"))
ML_RANDOM_STATE = int(os.getenv("ML_RANDOM_STATE", "42"))
ML_ENABLE_BASELINE = os.getenv("ML_ENABLE_BASELINE", "true").lower() in ("1", "true", "yes")
HISTORY_MAX = int(os.getenv("HISTORY_MAX", "60"))
# ESP currently transmits temperature, humidity, MQ-4/gas — not pressure.
ML_FEATURES = tuple(
    f.strip()
    for f in os.getenv("ML_FEATURES", "temperature,humidity,mq4").split(",")
    if f.strip()
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ML_DATASET_ABS = ML_DATASET_PATH if os.path.isabs(ML_DATASET_PATH) else os.path.join(BASE_DIR, ML_DATASET_PATH)
ML_MODEL_ABS = ML_MODEL_PATH if os.path.isabs(ML_MODEL_PATH) else os.path.join(BASE_DIR, ML_MODEL_PATH)

try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, classification_report
    from sklearn.model_selection import train_test_split

    SKLEARN_AVAILABLE = True
except ImportError:
    joblib = None  # type: ignore
    RandomForestClassifier = None  # type: ignore
    SKLEARN_AVAILABLE = False


def _esp_base_url() -> str:
    return f"http://{ESP_IP}:{ESP_PORT}"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("forest-fire-backend")

# ---------------------------------------------------------------------------
# Observed ESP formats (from ESP8266_Gateway_NoPlugin.ino — not invented)
#
# HTTP GET /api/data JSON:
#   {
#     "timestamp": <millis>,
#     "node_online": true|false,
#     "last_seen": <millis>,
#     "gateway_ip": "<ip>",
#     "uptime": <millis>,
#     "sensors": {"temperature": 25.5, "humidity": 60.2, "smoke": 45, "gas": 23}
#                | null,
#     "last_data": "Temp:25.5,Hum:60.2,Smoke:45,Gas:23"
#   }
#
# LoRa last_data (gateway parseSensorData):
#   Temp:<float>,Hum:<float>,Smoke:<int>,Gas:<int>
#
# Legacy HTML / LoRa (esp_scraper_server.py, still parsed if seen):
#   NODE<id>:T=<float>,H=<float>,MQ=<int>,F=<int>,FP=<float>
# ---------------------------------------------------------------------------

LORA_KEY_VALUE_RE = re.compile(
    r"(Temp|Humidity|Hum|Smoke|Gas|MQ|Pressure|Press|FP|T|H|F|P)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
NODE_PACKET_RE = re.compile(
    r"NODE(\d+)\s*:\s*T=([0-9.]+)\s*,\s*H=([0-9.]+)\s*,\s*MQ=([0-9.]+)"
    r"(?:\s*,\s*F=([0-9.]+))?(?:\s*,\s*FP=([0-9.]+))?",
    re.IGNORECASE,
)
HTML_LAST_DATA_RE = re.compile(
    r"<strong>\s*Last Data:\s*</strong>\s*<br\s*/?>\s*([^<]+)",
    re.IGNORECASE,
)

ALERT_RANK = {
    "minimal": 0,
    "low": 1,
    "moderate": 2,
    "high": 3,
    "critical": 4,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> Optional[int]:
    number = to_float(value)
    if number is None:
        return None
    try:
        return int(round(number))
    except (TypeError, ValueError, OverflowError):
        return None


def empty_sensors() -> dict[str, Optional[float]]:
    return {
        "temperature": None,
        "humidity": None,
        "pressure": None,
        "gas": None,
        "mq4": None,
        "smoke": None,
        "flame": None,
    }


class FireRiskCalculator:
    """Single deterministic environmental risk score (migrated from the scraper).

    Uses whatever real ESP values are present. Missing sensors are omitted and
    remaining weights are renormalized. Pressure is included only when the ESP
    actually provides it.
    """

    def __init__(self) -> None:
        self.base_weights = {
            "temperature": RISK_WEIGHT_TEMPERATURE,
            "humidity": RISK_WEIGHT_HUMIDITY,
            "gas": RISK_WEIGHT_GAS,
            "pressure": RISK_WEIGHT_PRESSURE,
        }

    def assess(self, sensors: dict[str, Any]) -> dict[str, Any]:
        temperature = to_float(sensors.get("temperature"))
        humidity = to_float(sensors.get("humidity"))
        gas = to_float(sensors.get("mq4"))
        if gas is None:
            gas = to_float(sensors.get("gas"))
        pressure = to_float(sensors.get("pressure"))

        components: dict[str, float] = {}
        used: dict[str, float] = {}
        missing: list[str] = []

        if temperature is None:
            missing.append("temperature")
        else:
            used["temperature"] = temperature
            components["temperature"] = self._temp_component(temperature)

        if humidity is None:
            missing.append("humidity")
        else:
            used["humidity"] = humidity
            components["humidity"] = self._humidity_component(humidity)

        if gas is None:
            missing.append("mq4")
        else:
            used["mq4"] = gas
            components["gas"] = self._gas_component(gas)

        if pressure is None:
            missing.append("pressure")
        else:
            used["pressure"] = pressure
            components["pressure"] = self._pressure_component(pressure)

        if not components:
            return {
                "score": None,
                "level": None,
                "used_sensors": used,
                "missing_sensors": missing,
                "weights": {},
                "methodology": "weighted_environmental_index",
            }

        weights = {name: self.base_weights[name] for name in components}
        total_w = sum(weights.values()) or 1.0
        weights = {name: value / total_w for name, value in weights.items()}

        score = sum(components[name] * weights[name] for name in components) * 100.0

        if temperature is not None and humidity is not None:
            if temperature > RISK_TEMP_MID + 2 and humidity < RISK_HUM_LOW:
                score *= RISK_COMBO_TEMP_HUM_MULT
        if temperature is not None and gas is not None:
            if temperature > RISK_TEMP_MID and gas > RISK_GAS_HIGH - 20:
                score *= RISK_COMBO_TEMP_GAS_MULT
        if humidity is not None and gas is not None:
            if humidity < RISK_HUM_LOW - 10 and gas > RISK_GAS_MID:
                score *= RISK_COMBO_HUM_GAS_MULT

        score = round(min(100.0, max(0.0, score)), 1)
        return {
            "score": score,
            "level": self.get_risk_level(score),
            "used_sensors": used,
            "missing_sensors": missing,
            "weights": {k: round(v, 4) for k, v in weights.items()},
            "methodology": "weighted_environmental_index",
        }

    @staticmethod
    def _temp_component(temperature: float) -> float:
        if temperature <= RISK_TEMP_LOW:
            return 0.0
        if temperature <= RISK_TEMP_MID:
            return 0.2
        if temperature <= RISK_TEMP_HIGH:
            return 0.6
        return 0.9

    @staticmethod
    def _humidity_component(humidity: float) -> float:
        if humidity >= RISK_HUM_HIGH:
            return 0.0
        if humidity >= RISK_HUM_MID:
            return 0.2
        if humidity >= RISK_HUM_LOW:
            return 0.6
        return 0.9

    @staticmethod
    def _gas_component(gas: float) -> float:
        if gas <= RISK_GAS_LOW:
            return 0.0
        if gas <= RISK_GAS_MID:
            return 0.3
        if gas <= RISK_GAS_HIGH:
            return 0.7
        return 0.9

    @staticmethod
    def _pressure_component(pressure: float) -> float:
        # Used only when a real pressure reading exists. Lower pressure slightly
        # increases the environmental index; this is a weak optional term.
        if pressure >= RISK_PRESSURE_MID:
            return 0.0
        if pressure >= RISK_PRESSURE_LOW:
            return 0.3
        return 0.6

    @staticmethod
    def get_risk_level(score: Optional[float]) -> Optional[str]:
        if score is None:
            return None
        if score < RISK_LEVEL_LOW:
            return "minimal"
        if score < RISK_LEVEL_MODERATE:
            return "low"
        if score < RISK_LEVEL_HIGH:
            return "moderate"
        if score < RISK_LEVEL_CRITICAL:
            return "high"
        return "critical"


def _mq4_from_sensors(sensors: dict[str, Any]) -> Optional[float]:
    value = to_float(sensors.get("mq4"))
    if value is None:
        value = to_float(sensors.get("gas"))
    return value


def _feature_value(name: str, sensors: dict[str, Any]) -> Optional[float]:
    if name in ("mq4", "gas"):
        return _mq4_from_sensors(sensors)
    return to_float(sensors.get(name))


class FireClassifier:
    """Random Forest fire-possibility classifier.

    There is no labeled dataset in this repository. Until a real CSV is placed
    at ML_DATASET_PATH, the model is a clearly marked experimental baseline
    fit on a deterministic heuristic grid — not a validated detector.
    """

    def __init__(self) -> None:
        self.model = None
        self.features = list(ML_FEATURES)
        self.status = "unavailable"
        self.experimental = True
        self.validated = False
        self.dataset_source = None
        self.metrics: dict[str, Any] = {}
        self.error: Optional[str] = None
        self._load_or_train()

    def unavailable_result(self, reason: str, sensors: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        missing = []
        if sensors is not None:
            missing = [name for name in self.features if _feature_value(name, sensors) is None]
        return {
            "prediction": None,
            "probabilities": None,
            "model_status": self.status,
            "experimental": self.experimental,
            "validated": False,
            "classes": list(FIRE_CLASSES),
            "features": list(self.features),
            "missing_features": missing,
            "reason": reason,
            "dataset_source": self.dataset_source,
        }

    def predict(self, sensors: dict[str, Any]) -> dict[str, Any]:
        if self.model is None or not SKLEARN_AVAILABLE:
            return self.unavailable_result(self.error or "model_unavailable", sensors)

        vector: list[float] = []
        missing: list[str] = []
        used: dict[str, float] = {}
        for name in self.features:
            value = _feature_value(name, sensors)
            if value is None:
                missing.append(name)
            else:
                used[name] = value
                vector.append(value)

        if missing:
            result = self.unavailable_result("missing_features", sensors)
            result["model_status"] = self.status
            result["used_features"] = used
            return result

        try:
            raw = self.model.predict_proba([vector])[0]
            labeled = self.model.classes_
            probabilities = {name: 0.0 for name in FIRE_CLASSES}
            for cls, prob in zip(labeled, raw):
                key = str(cls)
                if key in probabilities:
                    probabilities[key] = round(float(prob), 4)
            prediction = max(probabilities, key=probabilities.get)
            return {
                "prediction": prediction,
                "probabilities": probabilities,
                "model_status": self.status,
                "experimental": self.experimental,
                "validated": self.validated,
                "classes": list(FIRE_CLASSES),
                "features": list(self.features),
                "used_features": used,
                "missing_features": [],
                "dataset_source": self.dataset_source,
            }
        except Exception as exc:
            logger.error("Random Forest prediction failed: %s", exc)
            return self.unavailable_result(f"predict_failed: {exc}", sensors)

    def _load_or_train(self) -> None:
        if not SKLEARN_AVAILABLE:
            self.status = "unavailable"
            self.error = "sklearn_not_installed"
            logger.warning("sklearn is not installed; ML classifier unavailable")
            return

        if os.path.isfile(ML_DATASET_ABS):
            try:
                self._train_from_csv(ML_DATASET_ABS)
                return
            except Exception as exc:
                logger.error("Failed to train from %s: %s", ML_DATASET_ABS, exc)
                self.error = str(exc)

        if ML_ENABLE_BASELINE:
            try:
                self._train_baseline()
                return
            except Exception as exc:
                logger.error("Baseline Random Forest training failed: %s", exc)
                self.error = str(exc)

        self.status = "unavailable"
        self.error = self.error or "no_dataset_and_baseline_disabled"

    def _train_from_csv(self, path: str) -> None:
        import csv

        rows: list[list[float]] = []
        labels: list[str] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("dataset has no header row")
            fields = {name.strip().lower(): name for name in reader.fieldnames}
            label_col = fields.get("label") or fields.get("class") or fields.get("fire")
            if not label_col:
                raise ValueError("dataset must include a label/class column")
            for row in reader:
                try:
                    vector = []
                    skip = False
                    for feature in self.features:
                        raw = row.get(feature)
                        if raw is None and feature == "mq4":
                            raw = row.get("gas") or row.get("MQ") or row.get("mq")
                        if raw is None or str(raw).strip() == "":
                            skip = True
                            break
                        vector.append(float(raw))
                    if skip:
                        continue
                    label = self._normalize_label(row.get(label_col))
                    if label is None:
                        continue
                    rows.append(vector)
                    labels.append(label)
                except (TypeError, ValueError):
                    continue

        if len(rows) < 10:
            raise ValueError(f"dataset too small after cleaning ({len(rows)} rows)")

        self._fit(rows, labels, source=f"csv:{os.path.basename(path)}", trained=True)

    def _train_baseline(self) -> None:
        """Deterministic heuristic grid — architecture/smoke-test only, not real fire labels."""
        temperatures = (10, 18, 22, 25, 28, 32, 35, 38, 42, 48)
        humidities = (15, 25, 35, 45, 55, 65, 75, 90)
        gases = (20, 50, 80, 120, 160, 200, 260, 350)
        rows: list[list[float]] = []
        labels: list[str] = []
        for temperature in temperatures:
            for humidity in humidities:
                for gas in gases:
                    sample = {"temperature": temperature, "humidity": humidity, "mq4": gas}
                    vector = [_feature_value(name, sample) for name in self.features]
                    if any(v is None for v in vector):
                        continue
                    rows.append([float(v) for v in vector])  # type: ignore[arg-type]
                    labels.append(self._heuristic_label(temperature, humidity, gas))
        self._fit(rows, labels, source="heuristic_grid_baseline", trained=False)

    def _fit(self, rows: list[list[float]], labels: list[str], source: str, trained: bool) -> None:
        unique = sorted(set(labels), key=lambda name: FIRE_CLASSES.index(name) if name in FIRE_CLASSES else 99)
        if len(unique) < 2:
            raise ValueError("need at least two classes to train RandomForestClassifier")

        metrics: dict[str, Any] = {"n_samples": len(rows), "class_counts": {c: labels.count(c) for c in unique}}
        can_split = len(rows) >= 20 and min(labels.count(c) for c in unique) >= 2
        if can_split:
            x_train, x_test, y_train, y_test = train_test_split(
                rows,
                labels,
                test_size=0.25,
                random_state=ML_RANDOM_STATE,
                stratify=labels,
            )
        else:
            x_train, y_train, x_test, y_test = rows, labels, rows, labels

        model = RandomForestClassifier(
            n_estimators=ML_N_ESTIMATORS,
            random_state=ML_RANDOM_STATE,
            class_weight="balanced",
            n_jobs=1,
        )
        model.fit(x_train, y_train)
        predicted = model.predict(x_test)
        metrics["holdout_accuracy"] = round(float(accuracy_score(y_test, predicted)), 4)
        metrics["classification_report"] = classification_report(y_test, predicted, output_dict=True, zero_division=0)
        metrics["note"] = (
            "Holdout metrics on labeled CSV"
            if trained
            else "Self-check on heuristic grid only — not scientific validation"
        )

        self.model = model
        self.metrics = metrics
        self.dataset_source = source
        self.validated = False
        if trained:
            self.status = "trained"
            self.experimental = False
            logger.info(
                "Random Forest trained from CSV (%s samples, accuracy=%s). Not claimed validated without domain review.",
                metrics["n_samples"],
                metrics["holdout_accuracy"],
            )
        else:
            self.status = "baseline"
            self.experimental = True
            logger.warning(
                "No labeled dataset found. Using EXPERIMENTAL baseline Random Forest (%s heuristic samples). "
                "Do not treat this as a reliable fire detector. Place a CSV at %s to replace it.",
                metrics["n_samples"],
                ML_DATASET_ABS,
            )

        try:
            os.makedirs(os.path.dirname(ML_MODEL_ABS) or ".", exist_ok=True)
            joblib.dump(
                {
                    "model": model,
                    "features": self.features,
                    "classes": list(FIRE_CLASSES),
                    "status": self.status,
                    "experimental": self.experimental,
                    "dataset_source": source,
                    "metrics": metrics,
                },
                ML_MODEL_ABS,
            )
        except Exception as exc:
            logger.warning("Could not save model artifact: %s", exc)

    @staticmethod
    def _normalize_label(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().lower().replace("_", " ").replace("-", " ")
        mapping = {
            "none": "None",
            "no fire": "None",
            "no": "None",
            "0": "None",
            "potential": "Potential Fire",
            "potential fire": "Potential Fire",
            "possible": "Potential Fire",
            "1": "Potential Fire",
            "confirmed": "Confirmed Fire",
            "confirmed fire": "Confirmed Fire",
            "fire": "Confirmed Fire",
            "2": "Confirmed Fire",
        }
        return mapping.get(text)

    @staticmethod
    def _heuristic_label(temperature: float, humidity: float, gas: float) -> str:
        if temperature >= RISK_TEMP_HIGH + 3 and humidity <= RISK_HUM_LOW - 5 and gas >= RISK_GAS_HIGH:
            return "Confirmed Fire"
        flags = 0
        if temperature >= RISK_TEMP_MID:
            flags += 1
        if humidity <= RISK_HUM_MID:
            flags += 1
        if gas >= RISK_GAS_MID:
            flags += 1
        if temperature >= RISK_TEMP_HIGH or gas >= RISK_GAS_HIGH:
            flags += 1
        if flags >= 3:
            return "Potential Fire"
        return "None"


class EmailAlerter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_sent_at: Optional[datetime] = None
        self._last_level: Optional[str] = None

    def configured(self) -> bool:
        return bool(EMAIL_USER and EMAIL_PASSWORD and ALERT_EMAIL)

    def maybe_send(self, payload: dict[str, Any]) -> None:
        if not self.configured():
            return

        risk = payload.get("risk") or {}
        level = (risk.get("level") or "").lower()
        score = risk.get("score")
        if not level or score is None:
            return

        min_rank = ALERT_RANK.get(ALERT_MIN_LEVEL, ALERT_RANK["high"])
        if ALERT_RANK.get(level, 0) < min_rank:
            return

        now = utcnow()
        with self._lock:
            if self._last_sent_at is not None:
                elapsed = (now - self._last_sent_at).total_seconds()
                if elapsed < ALERT_COOLDOWN_SECONDS and self._last_level == level:
                    return
            self._last_sent_at = now
            self._last_level = level

        sensors = payload.get("sensors") or {}
        self.send(
            {
                "risk": score,
                "level": level.upper(),
                "temperature": sensors.get("temperature"),
                "humidity": sensors.get("humidity"),
                "pressure": sensors.get("pressure"),
                "gas": sensors.get("mq4") if sensors.get("mq4") is not None else sensors.get("gas"),
                "node": payload.get("node_id") or "gateway",
            }
        )

    def send(self, data: dict[str, Any]) -> bool:
        risk = data.get("risk")
        level = data.get("level")
        temperature = data.get("temperature")
        humidity = data.get("humidity")
        pressure = data.get("pressure")
        gas = data.get("gas")
        node = data.get("node")

        subject = f"Forest Fire {level} Alert - Fire Risk {risk}%"
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Forest Fire Detection Alert</h2>
            <h3>Alert Level: {level}</h3>
            <h2>Fire Risk: {risk}%</h2>
            <hr>
            <p><b>Node:</b> {node}</p>
            <p><b>Temperature:</b> {temperature} °C</p>
            <p><b>Humidity:</b> {humidity} %</p>
            <p><b>Pressure:</b> {pressure} hPa</p>
            <p><b>MQ-4 / gas:</b> {gas}</p>
            <hr>
            <p>Check the dashboard. Suppression is not activated automatically.</p>
        </body>
        </html>
        """

        message = MIMEMultipart()
        message["From"] = EMAIL_USER
        message["To"] = ALERT_EMAIL
        message["Subject"] = subject
        message.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.login(EMAIL_USER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_USER, ALERT_EMAIL, message.as_string())
            logger.info("Email alert sent: %s risk=%s", level, risk)
            return True
        except Exception as exc:
            logger.error("Email alert failed: %s", exc)
            return False


class EspClient:
    """Fetches and parses the live gateway without fabricating values."""

    def __init__(self) -> None:
        self.session = requests.Session()

    def fetch(self) -> dict[str, Any]:
        url = f"{_esp_base_url()}{ESP_DATA_PATH}"
        try:
            response = self.session.get(url, timeout=ESP_TIMEOUT)
            response.raise_for_status()
        except requests.Timeout as exc:
            raise EspFetchError("timeout", f"ESP connection timed out: {exc}") from exc
        except requests.RequestException as exc:
            raise EspFetchError("offline", f"ESP unreachable: {exc}") from exc

        content_type = (response.headers.get("Content-Type") or "").lower()
        text = response.text or ""

        if "application/json" in content_type or text.lstrip().startswith("{"):
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise EspFetchError("malformed", f"ESP JSON was malformed: {exc}") from exc
            if not isinstance(payload, dict):
                raise EspFetchError("malformed", "ESP JSON was not an object")
            return self._from_api_json(payload, text)

        html_match = HTML_LAST_DATA_RE.search(text)
        if html_match:
            last_data = html_match.group(1).strip()
            return self._from_raw_packet(last_data, source="html")

        raise EspFetchError("malformed", "ESP response was not JSON /api/data and had no Last Data HTML")

    def deploy(self) -> tuple[bool, str, Optional[int]]:
        url = f"{_esp_base_url()}{ESP_DEPLOY_PATH}"
        try:
            response = self.session.post(url, timeout=ESP_TIMEOUT, allow_redirects=False)
            if response.status_code in (200, 303):
                return True, "DEPLOY command sent to ESP gateway (LoRa)", response.status_code
            return False, f"ESP returned HTTP {response.status_code}", response.status_code
        except requests.Timeout:
            return False, "ESP deploy timed out", None
        except requests.RequestException as exc:
            return False, f"ESP deploy failed: {exc}", None

    def _from_api_json(self, payload: dict[str, Any], raw_text: str) -> dict[str, Any]:
        sensors = empty_sensors()
        parse_error: Optional[str] = None
        node_id: Optional[str] = None
        fire_probability: Optional[float] = None
        last_data = payload.get("last_data")
        if last_data is not None:
            last_data = str(last_data)

        json_sensors = payload.get("sensors")
        if isinstance(json_sensors, dict):
            sensors["temperature"] = to_float(json_sensors.get("temperature"))
            sensors["humidity"] = to_float(json_sensors.get("humidity"))
            sensors["pressure"] = to_float(
                json_sensors.get("pressure")
                if "pressure" in json_sensors
                else json_sensors.get("atmospheric_pressure")
            )
            gas = to_float(json_sensors.get("gas"))
            if gas is None:
                gas = to_float(json_sensors.get("mq4") if "mq4" in json_sensors else json_sensors.get("mq-4"))
            sensors["gas"] = gas
            sensors["mq4"] = gas
            sensors["smoke"] = to_float(json_sensors.get("smoke"))
            sensors["flame"] = to_float(json_sensors.get("flame"))
        elif json_sensors not in (None,):
            parse_error = "sensors field was present but not an object"

        if last_data:
            packet = self._parse_packet_string(last_data)
            node_id = packet.get("node_id")
            fire_probability = packet.get("fire_probability")
            for key, value in packet["sensors"].items():
                if sensors.get(key) is None and value is not None:
                    sensors[key] = value

        return {
            "sensors": sensors,
            "raw_message": last_data,
            "node_id": node_id,
            "fire_probability": fire_probability,
            "node_online": payload.get("node_online"),
            "gateway_ip": payload.get("gateway_ip"),
            "uptime_ms": to_int(payload.get("uptime")),
            "last_seen_ms": to_int(payload.get("last_seen")),
            "esp_timestamp_ms": to_int(payload.get("timestamp")),
            "parse_error": parse_error,
            "source": "json",
            "raw_http": raw_text[:2000],
        }

    def _from_raw_packet(self, last_data: str, source: str) -> dict[str, Any]:
        packet = self._parse_packet_string(last_data)
        return {
            "sensors": packet["sensors"],
            "raw_message": last_data,
            "node_id": packet.get("node_id"),
            "fire_probability": packet.get("fire_probability"),
            "node_online": None,
            "gateway_ip": None,
            "uptime_ms": None,
            "last_seen_ms": None,
            "esp_timestamp_ms": None,
            "parse_error": packet.get("parse_error"),
            "source": source,
            "raw_http": last_data,
        }

    def _parse_packet_string(self, data: str) -> dict[str, Any]:
        sensors = empty_sensors()
        node_id: Optional[str] = None
        fire_probability: Optional[float] = None
        parse_error: Optional[str] = None

        stripped = (data or "").strip()
        if not stripped or stripped.upper() == "PING":
            return {
                "sensors": sensors,
                "node_id": None,
                "fire_probability": None,
                "parse_error": None if not stripped else "heartbeat PING (no sensor fields)",
            }

        node_match = NODE_PACKET_RE.search(stripped)
        if node_match:
            node_id = f"NODE{node_match.group(1)}"
            sensors["temperature"] = to_float(node_match.group(2))
            sensors["humidity"] = to_float(node_match.group(3))
            gas = to_float(node_match.group(4))
            sensors["gas"] = gas
            sensors["mq4"] = gas
            if node_match.group(5) is not None:
                sensors["flame"] = to_float(node_match.group(5))
            if node_match.group(6) is not None:
                fire_probability = to_float(node_match.group(6))

        for match in LORA_KEY_VALUE_RE.finditer(stripped):
            key = match.group(1).lower()
            value = match.group(2)
            if key in ("temp", "t") and key != "fp":
                if key == "t" and sensors["temperature"] is not None:
                    continue
                sensors["temperature"] = to_float(value)
            elif key in ("hum", "humidity", "h"):
                if key == "h" and sensors["humidity"] is not None:
                    continue
                sensors["humidity"] = to_float(value)
            elif key in ("smoke",):
                sensors["smoke"] = to_float(value)
            elif key in ("gas", "mq"):
                gas = to_float(value)
                sensors["gas"] = gas
                sensors["mq4"] = gas
            elif key in ("press", "pressure"):
                sensors["pressure"] = to_float(value)
            elif key == "p" and "press" in stripped.lower():
                sensors["pressure"] = to_float(value)
            elif key == "f" and sensors["flame"] is None:
                sensors["flame"] = to_float(value)
            elif key == "fp":
                fire_probability = to_float(value)

        if all(v is None for v in sensors.values()) and fire_probability is None:
            parse_error = "packet contained no recognized sensor fields"

        return {
            "sensors": sensors,
            "node_id": node_id,
            "fire_probability": fire_probability,
            "parse_error": parse_error,
        }


class EspFetchError(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class SensorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = {
            "backend": "ok",
            "esp_status": "waiting",
            "esp_reachable": False,
            "stale": True,
            "last_successful_reading": None,
            "last_attempt": None,
            "last_error": None,
            "node_id": None,
            "node_online": None,
            "gateway_ip": None,
            "uptime_ms": None,
            "last_seen_ms": None,
            "esp_timestamp_ms": None,
            "sensors": empty_sensors(),
            "risk": {"score": None, "level": None, "used_sensors": {}, "missing_sensors": []},
            "ml": {
                "prediction": None,
                "probabilities": None,
                "model_status": "unavailable",
            },
            "raw_message": None,
            "parse_error": None,
            "source": None,
        }
        self._history: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = deepcopy(self._state)
        state["stale"] = self._is_stale(state)
        if state["stale"] and state["esp_status"] in ("ok", "live"):
            state["esp_status"] = "stale"
        return state

    def _is_stale(self, state: dict[str, Any]) -> bool:
        last = state.get("last_successful_reading")
        if last is None:
            return True
        last_dt = datetime.fromisoformat(last)
        return (utcnow() - last_dt).total_seconds() > ESP_STALE_SECONDS

    def record_success(
        self,
        parsed: dict[str, Any],
        risk: dict[str, Any],
        ml: dict[str, Any],
    ) -> dict[str, Any]:
        now = isoformat(utcnow())
        with self._lock:
            self._state.update(
                {
                    "backend": "ok",
                    "esp_status": "ok",
                    "esp_reachable": True,
                    "stale": False,
                    "last_successful_reading": now,
                    "last_attempt": now,
                    "last_error": None,
                    "node_id": parsed.get("node_id"),
                    "node_online": parsed.get("node_online"),
                    "gateway_ip": parsed.get("gateway_ip"),
                    "uptime_ms": parsed.get("uptime_ms"),
                    "last_seen_ms": parsed.get("last_seen_ms"),
                    "esp_timestamp_ms": parsed.get("esp_timestamp_ms"),
                    "sensors": parsed.get("sensors") or empty_sensors(),
                    "risk": risk,
                    "ml": ml,
                    "raw_message": parsed.get("raw_message"),
                    "parse_error": parsed.get("parse_error"),
                    "source": parsed.get("source"),
                }
            )
            entry = {
                "timestamp": now,
                "temperature": (parsed.get("sensors") or {}).get("temperature"),
                "humidity": (parsed.get("sensors") or {}).get("humidity"),
                "pressure": (parsed.get("sensors") or {}).get("pressure"),
                "mq4": (parsed.get("sensors") or {}).get("mq4"),
                "risk_score": (risk or {}).get("score"),
                "risk_level": (risk or {}).get("level"),
                "prediction": (ml or {}).get("prediction"),
            }
            self._history.append(entry)
            if len(self._history) > HISTORY_MAX:
                self._history = self._history[-HISTORY_MAX:]
            return deepcopy(self._state)

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._history)

    def record_failure(self, status: str, message: str) -> None:
        now = isoformat(utcnow())
        with self._lock:
            self._state["backend"] = "ok"
            self._state["esp_status"] = status
            self._state["esp_reachable"] = False
            self._state["last_attempt"] = now
            self._state["last_error"] = message
            last = self._state.get("last_successful_reading")
            if last is None:
                self._state["stale"] = True
            else:
                self._state["stale"] = (
                    utcnow() - datetime.fromisoformat(last)
                ).total_seconds() > ESP_STALE_SECONDS


class Poller:
    def __init__(
        self,
        client: EspClient,
        store: SensorStore,
        calculator: FireRiskCalculator,
        classifier: FireClassifier,
        alerter: EmailAlerter,
    ) -> None:
        self.client = client
        self.store = store
        self.calculator = calculator
        self.classifier = classifier
        self.alerter = alerter
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="esp-poller", daemon=True)
        self._thread.start()
        logger.info("ESP poller started (%s every %ss, timeout %ss)", _esp_base_url(), ESP_POLL_INTERVAL, ESP_TIMEOUT)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                logger.exception("Unhandled poller error: %s", exc)
                self.store.record_failure("error", str(exc))
            self._stop.wait(ESP_POLL_INTERVAL)

    def _poll_once(self) -> None:
        try:
            parsed = self.client.fetch()
        except EspFetchError as exc:
            logger.warning("%s", exc.message)
            self.store.record_failure(exc.status, exc.message)
            return

        sensors = parsed.get("sensors") or empty_sensors()
        risk = self.calculator.assess(sensors)
        ml = self.classifier.predict(sensors)
        if parsed.get("fire_probability") is not None:
            ml["esp_node_fire_probability"] = parsed.get("fire_probability")
        snapshot = self.store.record_success(parsed, risk, ml)
        logger.info(
            "ESP reading T=%s H=%s P=%s MQ4=%s risk=%s ml=%s",
            sensors.get("temperature"),
            sensors.get("humidity"),
            sensors.get("pressure"),
            sensors.get("mq4"),
            risk.get("score"),
            ml.get("prediction"),
        )
        try:
            self.alerter.maybe_send(snapshot)
        except Exception as exc:
            logger.error("Alert dispatch failed: %s", exc)


app = Flask(__name__)
CORS(app)

esp_client = EspClient()
risk_calculator = FireRiskCalculator()
fire_classifier = FireClassifier()
email_alerter = EmailAlerter()
sensor_store = SensorStore()
poller = Poller(esp_client, sensor_store, risk_calculator, fire_classifier, email_alerter)


def _started_by_reloader() -> bool:
    return os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not FLASK_DEBUG


@app.before_request
def _ensure_poller() -> None:
    poller.start()


def _api_data_payload() -> dict[str, Any]:
    state = sensor_store.snapshot()
    sensors = state["sensors"]
    node_online = state.get("node_online")
    if node_online is None:
        node_online = bool(state.get("esp_reachable")) and not state.get("stale")

    return {
        "timestamp": isoformat(utcnow()),
        "esp": {
            "ip": ESP_IP,
            "port": ESP_PORT,
            "reachable": state["esp_reachable"],
            "status": state["esp_status"],
            "stale": state["stale"],
            "gateway_ip": state.get("gateway_ip"),
            "uptime_ms": state.get("uptime_ms"),
            "node_online": node_online,
            "last_seen_ms": state.get("last_seen_ms"),
            "last_error": state.get("last_error"),
        },
        "node_id": state.get("node_id"),
        "sensors": {
            "temperature": sensors.get("temperature"),
            "humidity": sensors.get("humidity"),
            "pressure": sensors.get("pressure"),
            "atmospheric_pressure": sensors.get("pressure"),
            "gas": sensors.get("gas"),
            "mq4": sensors.get("mq4"),
            "smoke": sensors.get("smoke"),
            "flame": sensors.get("flame"),
        },
        "risk": state.get("risk"),
        "ml": state.get("ml"),
        "prediction": (state.get("ml") or {}).get("prediction"),
        "fire_probability": (state.get("ml") or {}).get("probabilities"),
        "raw_message": state.get("raw_message"),
        "parse_error": state.get("parse_error"),
        "last_successful_reading": state.get("last_successful_reading"),
        "history": sensor_store.history(),
    }


@app.get("/api/data")
def api_data():
    try:
        return jsonify(_api_data_payload())
    except Exception as exc:
        logger.exception("GET /api/data failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500


@app.get("/api/history")
def api_history():
    try:
        return jsonify({"history": sensor_store.history()})
    except Exception as exc:
        logger.exception("GET /api/history failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500


@app.get("/api/risk")
def api_risk():
    try:
        payload = _api_data_payload()
        return jsonify(
            {
                "timestamp": payload["timestamp"],
                "esp_status": payload["esp"]["status"],
                "esp_reachable": payload["esp"]["reachable"],
                "stale": payload["esp"]["stale"],
                "sensors": payload["sensors"],
                "risk": payload["risk"],
                "ml": payload["ml"],
                "prediction": payload["prediction"],
                "automatic_suppression": False,
            }
        )
    except Exception as exc:
        logger.exception("GET /api/risk failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500


@app.get("/api/health")
def api_health():
    try:
        state = sensor_store.snapshot()
        healthy = state["esp_reachable"] and not state["stale"]
        return jsonify(
            {
                "backend": "ok",
                "status": "ok" if healthy else state["esp_status"],
                "esp": {
                    "ip": ESP_IP,
                    "reachable": state["esp_reachable"],
                    "status": state["esp_status"],
                    "stale": state["stale"],
                    "offline": not state["esp_reachable"],
                },
                "last_successful_reading": state.get("last_successful_reading"),
                "last_attempt": state.get("last_attempt"),
                "last_error": state.get("last_error"),
                "poll_interval_seconds": ESP_POLL_INTERVAL,
                "timeout_seconds": ESP_TIMEOUT,
                "stale_after_seconds": ESP_STALE_SECONDS,
            }
        ), (200 if state["backend"] == "ok" else 503)
    except Exception as exc:
        logger.exception("GET /api/health failed: %s", exc)
        return jsonify({"backend": "error", "message": str(exc)}), 500


@app.post("/api/deploy")
def api_deploy():
    """Manual suppression only — never called by the poller."""
    try:
        ok, message, status_code = esp_client.deploy()
        body = {
            "status": "success" if ok else "error",
            "message": message,
            "esp_http_status": status_code,
            "automatic": False,
            "ml_does_not_activate_suppression": True,
        }
        return jsonify(body), (200 if ok else 502)
    except Exception as exc:
        logger.exception("POST /api/deploy failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc), "automatic": False}), 500


@app.get("/logs")
@app.get("/logs.html")
def logs_page():
    """Serve the logs dashboard through the Flask backend."""
    return send_from_directory(BASE_DIR, "logs.html")


@app.get("/settings")
@app.get("/settings.html")
def settings_page():
    """Serve the settings page through the Flask backend."""
    return send_from_directory(BASE_DIR, "settings.html")


@app.get("/about")
@app.get("/about.html")
def about_page():
    """Serve the about page through the Flask backend."""
    return send_from_directory(BASE_DIR, "about.html")


@app.get("/")
@app.get("/index.html")
def root():
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.isfile(index_path):
        return send_from_directory(BASE_DIR, "index.html")
    return jsonify({"service": "forest-fire-backend", "docs": ["/api/data", "/api/health", "/api/risk", "/api/deploy"]})


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not_found", "path": request.path}), 404
    return jsonify({"error": "not_found"}), 404


@app.errorhandler(Exception)
def unhandled(error):
    logger.exception("Unhandled Flask error: %s", error)
    return jsonify({"error": "internal_error", "message": str(error)}), 500


if __name__ == "__main__":
    logger.info("Starting backend on %s:%s — ESP %s", FLASK_HOST, FLASK_PORT, _esp_base_url())
    if _started_by_reloader():
        poller.start()
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG, use_reloader=FLASK_DEBUG)