"""
Django settings for config project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables from the project-root .env.
# The path is given explicitly: a bare load_dotenv() discovers the file by
# walking up from the *calling frame*, which does not resolve reliably under
# pytest's import machinery — settings then fell back to empty DB credentials.
load_dotenv(BASE_DIR / ".env")


# ==============================
# SECURITY SETTINGS
# ==============================

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

DEBUG = True
ALLOWED_HOSTS = ["*"]


# ==============================
# APPLICATION DEFINITION
# ==============================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',

    'apps.core.apps.CoreConfig',
    'apps.accounts.apps.AccountsConfig',
    'apps.memberships.apps.MembershipsConfig',
    'apps.assessments.apps.AssessmentsConfig',
    'apps.platform_sessions.apps.PlatformSessionsConfig',
    'apps.lifecycles.apps.LifecyclesConfig',
    'apps.monitoring.apps.MonitoringConfig',
    'apps.tenants.apps.TenantsConfig',
    'apps.authority.apps.AuthorityConfig',
    'apps.dashboard.apps.DashboardConfig',

    'apps.bookings',
    'apps.payments',
    'apps.attendance',
    'apps.sessions',
    'apps.communications.apps.CommunicationsConfig',
    'apps.analytics.apps.AnalyticsConfig',
    'apps.actions.apps.ActionsConfig',
    'apps.settings.roles.apps.RolesConfig',
    'apps.settings.vocabulary.apps.VocabularyConfig',
    'apps.settings.branding.apps.BrandingConfig',
    'apps.settings.whatsapp.apps.WhatsAppSettingsConfig',
    'apps.renewals.apps.RenewalsConfig',
    'apps.engagement.apps.EngagementConfig',
    'apps.revenue.apps.RevenueConfig',

    'apps.audit.apps.AuditConfig',

    # Financial + vertical system
    'apps.verticals.apps.VerticalsConfig',
    'apps.catalog.apps.CatalogConfig',
    'apps.enrollments.apps.EnrollmentsConfig',
    'apps.activity.apps.ActivityConfig',
    'apps.expenses.apps.ExpensesConfig',
    'apps.payouts.apps.PayoutsConfig',
    'apps.documents.apps.DocumentsConfig',
    'apps.reporting.apps.ReportingConfig',

    'members',
    'crm.apps.CrmConfig',

    'platform_core',
    'apps.intake.apps.IntakeConfig',
]


# ==============================
# MIDDLEWARE (CORRECT ORDER)
# ==============================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',

    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',   # ✅ BEFORE auth

    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.core.middleware.TenantMiddleware',

    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


ROOT_URLCONF = 'config.urls'


# ==============================
# TEMPLATES
# ==============================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',  # IMPORTANT
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.settings.context_processors.vocabulary_labels',
                'apps.settings.context_processors.tenant_branding',
            ],
        },
    },
]


WSGI_APPLICATION = 'config.wsgi.application'


# ==============================
# DATABASE
# ==============================

# Credentials come from the environment (.env locally, real env vars in
# production). They were previously hard-coded here, which meant a deployed
# server tried to reach 127.0.0.1:5433 with a throwaway password.
# The defaults below are LOCAL DEVELOPMENT ONLY — production must set every
# DB_* variable explicitly (see .env.example).
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'saas_db'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '5433'),
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
        'OPTIONS': (
            {'sslmode': os.getenv('DB_SSLMODE')}
            if os.getenv('DB_SSLMODE') else {}
        ),
    }
}


# ==============================
# PASSWORD VALIDATION
# ==============================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ==============================
# INTERNATIONALIZATION
# ==============================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True
USE_TZ = True


# ==============================
# STATIC FILES
# ==============================

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ==============================
# AUTH
# ==============================

LOGIN_URL = "/login/"
LOGOUT_REDIRECT_URL = "/login/"

AUTH_USER_MODEL = "accounts.User"
TENANT_MODEL = "tenants.Tenant"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]


# ==============================
# REST FRAMEWORK
# ==============================

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}


# ==============================
# SECURITY (DEV SAFE)
# ==============================

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# 🔥 IMPORTANT FIXES
CSRF_COOKIE_HTTPONLY = False   # ✅ MUST BE FALSE
SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

SECURE_REFERRER_POLICY = "same-origin"

# Optional safety
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# ==============================
# SITE URL — used to build absolute URLs in emails (logo, CTAs)
# Override in production: SITE_URL = 'https://app.yourdomain.com'
# ==============================

SITE_URL = os.environ.get('SITE_URL', 'http://localhost:8000')

# Prefix email subject with brand name: "[Acme Gym] Payment Successful"
# Set to True per-environment to enable.
COMMS_BRAND_EMAIL_SUBJECT = False

# ==============================
# PLATFORM TENANT
# ==============================
# ANJASI's own messaging — studio onboarding, subscription invoices, service
# notices — runs through the ordinary communications engine under an internal
# tenant flagged is_platform=True, so templates, trigger rules, logging and
# retry are all reused. See apps/core/platform.py for the rationale.
#
# Provision with:  manage.py ensure_platform_tenant

PLATFORM_TENANT_NAME = os.environ.get("PLATFORM_TENANT_NAME", "ANJASI")
PLATFORM_TENANT_SUBDOMAIN = os.environ.get("PLATFORM_TENANT_SUBDOMAIN", "anjasi")

# ==============================
# EMAIL
# ==============================
# Routed through Django's own email framework rather than a provider SDK, so
# AWS SES is reached over its SMTP interface and the provider can be swapped
# (SES / SendGrid / Mailgun / a local relay) by changing environment variables
# alone — no code change and no extra dependency.
#
# With EMAIL_HOST unset the adapter falls back to logging, so development and
# the test-suite run without credentials.

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").strip().lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "False").strip().lower() == "true"
# Never let a stalled SMTP handshake hang the request thread.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# ==============================
# RAZORPAY (global dev fallback — override per-tenant via TenantPaymentConfig)
# ==============================

import os

RAZORPAY_KEY_ID         = os.environ.get("RAZORPAY_KEY_ID",         "rzp_test_placeholder")
RAZORPAY_KEY_SECRET     = os.environ.get("RAZORPAY_KEY_SECRET",     "placeholder_secret")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "webhook_placeholder")

# ==============================
# PAYMENT FIELD ENCRYPTION
# ==============================
# Fernet key — generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# MUST be overridden in production via env var.
PAYMENTS_ENCRYPTION_KEY = os.environ.get(
    "PAYMENTS_ENCRYPTION_KEY",
    "BywK4uUFhAvnBYlTJi85zxFGzl74PSoGcVcbKPs_9bY=",  # dev default — change in production
)