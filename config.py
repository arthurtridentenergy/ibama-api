### config.py
"""Centralized configuration for the IBAMA API."""
import os

# --- External API settings ---
EXTERNAL_API_URL = os.getenv("API_EXTERNAL_URL", "https://api.vesselfinder.com/vessels")
EXTERNAL_API_KEY = os.getenv("API_EXTERNAL_KEY", "")

# --- Platform coordinates (converted from degrees/minutes to decimal) ---
PPM1_LAT = -(22 + 47.88 / 60)
PPM1_LON = -(40 + 45.75 / 60)
PCE1_LAT = -(22 + 42.50 / 60)
PCE1_LON = -(40 + 41.59 / 60)
P08_LAT = -(22 + 40.39 / 60)
P08_LON = -(40 + 32.79 / 60)
P65_LAT = -(22 + 42.11 / 60)
P65_LON = -(40 + 40.63 / 60)

PLATFORMS = [
    {
        "name": "PPM-1",
        "mmsi": "N/A",
        "license": "LO1572/2020",
        "validity": "11/7/2024",
        "observation": None,
        "latitude": PPM1_LAT,
        "longitude": PPM1_LON,
    },
    {
        "name": "PCE-1",
        "mmsi": "N/A",
        "license": "LO1572/2020",
        "validity": "11/7/2024",
        "observation": None,
        "latitude": PCE1_LAT,
        "longitude": PCE1_LON,
    },
    {
        "name": "P-08",
        "mmsi": "538001903",
        "license": "LO1572/2020",
        "validity": "11/7/2024",
        "observation": None,
        "latitude": P08_LAT,
        "longitude": P08_LON,
    },
    {
        "name": "P-65",
        "mmsi": "538003593",
        "license": "LO1572/2020",
        "validity": "11/7/2024",
        "observation": None,
        "latitude": P65_LAT,
        "longitude": P65_LON,
    },
]

# --- Vessel definitions ---
VESSELS = [
    {
        "name": "Maersk Ventura",
        "mmsi": "710002450",
        "license": "LO1572/2020",
        "validity": None,
        "observation": None,
        # last known static position, used as fallback
        "static_latitude": float(os.getenv("MAERSK_VENTURA_STATIC_LAT", -22.75)),
        "static_longitude": float(os.getenv("MAERSK_VENTURA_STATIC_LON", -40.75)),
    },
    {
        "name": "Maersk Vega",
        "mmsi": "710001720",
        "license": "LO1572/2020",
        "validity": None,
        "observation": None,
        "static_latitude": float(os.getenv("MAERSK_VEGA_STATIC_LAT", -22.72)),
        "static_longitude": float(os.getenv("MAERSK_VEGA_STATIC_LON", -40.70)),
    },
]

# --- Application settings ---
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
PORT = int(os.getenv("PORT", 8000))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
