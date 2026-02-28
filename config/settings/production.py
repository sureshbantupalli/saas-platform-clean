from .base import *

DEBUG = False

ALLOWED_HOSTS = ["your-domain.com"]  # Change later

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True