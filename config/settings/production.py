"""
PRODUCTION SETTINGS

IMPORTANT:
To activate this file, your production server MUST set:

    DJANGO_ENV=production

This loads production.py via config/settings/__init__.py
"""

from .base import *
import os

# ==========================================
# CORE PRODUCTION SWITCH
# ==========================================

DEBUG = False

# ==========================================
# REQUIRED .env VARIABLES FOR PRODUCTION
# ==========================================

"""
Production .env must include:

DJANGO_ENV=production
SECRET_KEY=very-long-production-secret
DEBUG=False

DB_NAME=your_prod_db
DB_USER=your_prod_user
DB_PASSWORD=secure_password
DB_HOST=localhost
DB_PORT=5432

ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
"""

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")

# ==========================================
# HTTPS & SECURITY ENFORCEMENT
# ==========================================

SECURE_SSL_REDIRECT = True

# Required when behind nginx / load balancer
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HTTP Strict Transport Security (1 year)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# ==========================================
# COOKIE SECURITY
# ==========================================

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# ==========================================
# CSRF TRUSTED ORIGINS
# ==========================================

CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")

# ==========================================
# PRODUCTION LOGGING
# ==========================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

# ==========================================
# 🔵 DEPLOYMENT CHECKLIST (FINAL)
# ==========================================

"""
Before deploying:

1. Ensure DJANGO_ENV=production is set.
2. Ensure DEBUG=False in .env.
3. Ensure ALLOWED_HOSTS contains real domain.
4. Ensure CSRF_TRUSTED_ORIGINS includes https://domain.
5. Run:
       python manage.py migrate
       python manage.py collectstatic
6. Use Gunicorn:
       gunicorn config.wsgi:application --bind 0.0.0.0:8000
7. Put behind Nginx.
8. Enable HTTPS (Certbot).
"""
