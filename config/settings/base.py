"""
Django settings for config project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


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

    'members',
    'crm',

    'platform_core',
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
            ],
        },
    },
]


WSGI_APPLICATION = 'config.wsgi.application'


# ==============================
# DATABASE
# ==============================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'saas_db',
        'USER': 'postgres',
        'PASSWORD': 'postgres123',
        'HOST': '127.0.0.1',
        'PORT': '5433',
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
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8000"]