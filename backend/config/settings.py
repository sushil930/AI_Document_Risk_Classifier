import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [x.strip() for x in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if x.strip()]
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.staticfiles", "corsheaders", "rest_framework", "apps.core"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "corsheaders.middleware.CorsMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND":"django.template.backends.django.DjangoTemplates","DIRS":[],"APP_DIRS":True,"OPTIONS":{"context_processors":["django.template.context_processors.request"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": dj_database_url.config(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600)}
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "private_uploads"
MEDIA_URL = "private/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES":[],"DEFAULT_PERMISSION_CLASSES":["rest_framework.permissions.AllowAny"],"DEFAULT_THROTTLE_CLASSES":["rest_framework.throttling.AnonRateThrottle"],"DEFAULT_THROTTLE_RATES":{"anon":"60/hour"},"DEFAULT_PAGINATION_CLASS":"rest_framework.pagination.PageNumberPagination","PAGE_SIZE":10}
CORS_ALLOWED_ORIGINS = [FRONTEND_ORIGIN]
CORS_ALLOW_CREDENTIALS = False
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
DATA_UPLOAD_MAX_MEMORY_SIZE = (MAX_UPLOAD_MB + 1) * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "500000"))
CLASSIFIER_MODEL_PATH = os.getenv("CLASSIFIER_MODEL_PATH", "")
CLASSIFIER_ALLOW_CANDIDATE = os.getenv("CLASSIFIER_ALLOW_CANDIDATE", "false").lower() == "true"
CLASSIFIER_MIN_WORDS = int(os.getenv("CLASSIFIER_MIN_WORDS", "20"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "180"))
GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-3.8-flash")
GEMINI_MODELS = [x.strip() for x in os.getenv("GEMINI_MODELS", "gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash").split(",") if x.strip()]
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", str(GEMINI_TIMEOUT_SECONDS)))
GROQ_DEFAULT_MODEL = os.getenv("GROQ_DEFAULT_MODEL", "openai/gpt-oss-120b")
GROQ_MODELS = [x.strip() for x in os.getenv("GROQ_MODELS", "openai/gpt-oss-120b").split(",") if x.strip()]
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", GROQ_DEFAULT_MODEL)
ANALYSIS_MODELS = GEMINI_MODELS + [f"groq:{model}" for model in GROQ_MODELS]
