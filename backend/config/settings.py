"""Django settings for the Weather-Aware Truck Routing API.

All deploy-specific values come from environment variables so the same code
runs locally (DEBUG on, Vite dev server proxying /api) and in production
(DEBUG off, Django serving the built React app via WhiteNoise).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,.onrender.com")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIST],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    }
]

# The app is stateless: no models, no sessions, no auth.
DATABASES = {}

# File-based so every gunicorn worker shares cached routes and forecasts, which
# keeps us well inside Open-Meteo's free per-minute quota.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get("CACHE_DIR", "/tmp/routecast-cache"),
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

STATIC_URL = "/static/"
# Serve the Vite build (index.html + /assets/*) from the site root. Files are
# pre-compressed at build time (`python -m whitenoise.compress frontend/dist`).
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_INDEX_FILE = True
# Vite fingerprints everything under /assets/, so it can be cached forever.
WHITENOISE_IMMUTABLE_FILE_TEST = r"^/?assets/.+-[0-9A-Za-z_-]{8}\.(js|css|svg|png|woff2?)$"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("API_RATE_LIMIT", "60/min")},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Third-party services -------------------------------------------------
OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
PHOTON_BASE_URL = os.environ.get("PHOTON_BASE_URL", "https://photon.komoot.io")
NOMINATIM_BASE_URL = os.environ.get("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
# Set OPEN_METEO_API_KEY to use the commercial endpoint (higher rate limits).
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")
OPEN_METEO_BASE_URL = os.environ.get(
    "OPEN_METEO_BASE_URL",
    "https://customer-api.open-meteo.com" if OPEN_METEO_API_KEY else "https://api.open-meteo.com",
)
HTTP_USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT", "RouteCast/1.0 (+https://github.com/Vsr4661/weather-aware-truck-routing)"
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
