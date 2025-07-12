from pathlib import Path
import os
import logging
from dotenv import load_dotenv
from decouple import config
import dj_database_url

NGROK_FULL_URL = "https://0d0e3e34c51c.ngrok-free.app"
NGROK_URI = "0d0e3e34c51c.ngrok-free.app"

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = config('SECRET_KEY')
DEBUG = False

ALLOWED_HOSTS = ['.herokuapp.com', 'localhost', '127.0.0.1']

# Allow Django to be embedded in an IFrame (required for Salesforce)
# X_FRAME_OPTIONS = 'ALLOWALL'

CSRF_COOKIE_SECURE = True 
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_AGE = 86400  
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

CORS_ALLOWED_ORIGINS = [
    NGROK_FULL_URL
]

# ✅ Allow all domains in development (Use only for testing)
CSRF_COOKIE_DOMAIN = None
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

CSRF_TRUSTED_ORIGINS = [
    NGROK_FULL_URL
]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cpq",
    "agents",
    "dashboard",
    "salesforce",
    "hubspot",
    'django.contrib.humanize',
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "agentcpq.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        'DIRS': [BASE_DIR / 'cpq' / 'templates'],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "agentcpq.wsgi.application"


# Database
DATABASES = {

    'default': dj_database_url.config(default=config('DATABASE_URL'))
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


STATICFILES_DIRS = [
     BASE_DIR / 'static'
]



# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "https://cdnjs.cloudflare.com")  # Allow scripts only from trusted sources
CSP_STYLE_SRC = ("'self'", "https://fonts.googleapis.com")  # Allow Google Fonts
CSP_FONT_SRC = ("'self'", "https://fonts.gstatic.com")  # Allow Google Fonts
CSP_IMG_SRC = ("'self'", "data:")  # Allow local images and data URIs
CSP_CONNECT_SRC = ("'self'",)  # Restrict API calls to your own server


# ✅ Set default logging level (change to INFO if you want fewer logs)
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG if needed
    format="%(levelname)s:%(name)s:%(message)s"
)

# ✅ Suppress noisy libraries (OpenAI, HTTPX, and HTTPCore)
# logging.getLogger("openai").setLevel(logging.WARNING)  # Hide OpenAI debug logs
logging.getLogger("httpx").setLevel(logging.WARNING)  # Suppress HTTP client logs
logging.getLogger("httpcore").setLevel(logging.WARNING)  # Suppress low-level HTTP logs

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Salesforce OAuth settings for your connected app
SALESFORCE_CLIENT_ID = os.getenv("SF_CID")
SALESFORCE_CLIENT_SECRET = os.getenv("SF_SECRET")
SALESFORCE_REDIRECT_URI = "https://b377-2607-fb91-a06-c34d-44ac-db3b-c577-9f3a.ngrok-free.app/salesforce/callback"
SALESFORCE_AUTH_URL = "https://login.salesforce.com/services/oauth2/authorize"
SALESFORCE_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

