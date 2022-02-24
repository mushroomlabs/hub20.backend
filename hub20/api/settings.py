import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(PROJECT_DIR)
SECRET_KEY = os.getenv("HUB20_SECRET_KEY")

DEBUG = "HUB20_DEBUG" in os.environ


ALLOWED_HOSTS = os.getenv("HUB20_ALLOWED_HOSTS", ["*"])

# Application definition

DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "channels",
    "corsheaders",
    "dj_rest_auth",
    "dj_rest_auth.registration",
    "django_celery_beat",
    "django_celery_results",
    "django_filters",
    "djmoney",
    "drf_link_header_pagination",
    "drf_yasg",
    "rest_framework",
    "rest_framework.authtoken",
    "taggit",
]

PROJECT_APPS = [
    "hub20.apps.admin.apps.Hub20AdminConfig",
    "admin_interface",
    "colorfield",
    "django.contrib.admin",
    "hub20.apps.blockchain",
    "hub20.apps.wallet",
    "hub20.apps.ethereum_money",
    "hub20.apps.raiden",
    "hub20.apps.core",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + PROJECT_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

APPEND_SLASHES = False
ROOT_URLCONF = os.getenv("HUB20_URLCONF_MODULE", "hub20.api.urls")
ASGI_APPLICATION = "hub20.api.asgi.application"
SERVE_OPENAPI_URLS = "HUB20_SERVE_OPENAPI_URLS" in os.environ or DEBUG


if ROOT_URLCONF == "hub20.admin.urls":
    X_FRAME_OPTIONS = "SAMEORIGIN"
    SILENCED_SYSTEM_CHECKS = ["security.W019"]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(PROJECT_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]


# Database
# https://docs.djangoproject.com/en/1.9/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",  # PostgreSQL is required
        "HOST": os.getenv("HUB20_DATABASE_HOST"),
        "PORT": os.getenv("HUB20_DATABASE_PORT", 5432),
        "NAME": os.getenv("HUB20_DATABASE_NAME"),
        "USER": os.getenv("HUB20_DATABASE_USER"),
        "PASSWORD": os.getenv("HUB20_DATABASE_PASSWORD"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"


# Both Channel Layer and the cache system will require a running redis
# server, so the only thing you can change here is the URL (host/port/db)


# Channel Configurations
CHANNEL_LAYER_BACKEND = "channels_redis.core.RedisChannelLayer"
CHANNEL_LAYER_URL = os.getenv("HUB20_CHANNEL_LAYER_URL", "redis://redis:6379/2")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": CHANNEL_LAYER_BACKEND,
        "CONFIG": {"hosts": (CHANNEL_LAYER_URL,)},
    }
}

# Cache configuration
CACHE_BACKEND = "django_redis.cache.RedisCache"
CACHE_LOCATION = os.getenv("HUB20_CACHE_LOCATION", "redis://redis:6379/1")
CACHE_OPTIONS = {"CLIENT_CLASS": "django_redis.client.DefaultClient"}
CACHES = {
    "default": {"BACKEND": CACHE_BACKEND, "LOCATION": CACHE_LOCATION, "OPTIONS": CACHE_OPTIONS}
}


# Celery can use redis and many other systems as its task broker (e.g,
# RabbitMQ). Given that we already have a running redis for cache and
# channel layers, we use the same server in the default configuration

# Celery configuration
CELERY_BROKER_URL = os.getenv("HUB20_BROKER_URL", "redis://redis:6379/0")


# This needs to be set up if you don't have a front-end proxy server
CORS_ORIGIN_ALLOW_ALL = "HUB20_CORS_HEADERS_ENABLED" in os.environ

# This ensures that requests are seen as secure when the proxy sets the header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Password validation
# https://docs.djangoproject.com/en/1.9/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Email
DEFAULT_FROM_EMAIL = os.getenv("HUB20_EMAIL_MAILER_ADDRESS")
EMAIL_BACKEND = os.getenv("HUB20_EMAIL_BACKEND")
EMAIL_HOST = os.getenv("HUB20_EMAIL_HOST")
EMAIL_PORT = os.getenv("HUB20_EMAIL_PORT")
EMAIL_HOST_USER = os.getenv("HUB20_EMAIL_SMTP_USERNAME")
EMAIL_HOST_PASSWORD = os.getenv("HUB20_EMAIL_SMTP_PASSWORD")
EMAIL_TIMEOUT = os.getenv("HUB20_EMAIL_TIMEOUT", 5)


# Internationalization
# https://docs.djangoproject.com/en/1.9/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


SITE_ID = 1
HUB20_SITE_DOMAIN = os.getenv("HUB20_SITE_DOMAIN")


# Rest Framework settings
REST_RENDERERS = ("BrowsableAPIRenderer", "JSONRenderer") if DEBUG else ("JSONRenderer",)
REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_RENDERER_CLASSES": [
        f"rest_framework.renderers.{renderer}" for renderer in REST_RENDERERS
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "drf_link_header_pagination.LinkHeaderPagination",
    "PAGE_SIZE": 250,
}

# REST Auth
REST_AUTH_SERIALIZERS = {
    "USER_DETAILS_SERIALIZER": "hub20.api.serializers.UserProfileSerializer",
}


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.9/howto/static-files/

STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
)

STATIC_URL = "/static/"
STATIC_ROOT = os.getenv("HUB20_STATIC_ROOT", os.path.abspath(os.path.join(BASE_DIR, "static")))

ADMIN_USERNAME = os.getenv("HUB20_ADMIN_USERNAME", "admin")


# Configuration of authentication/signup/registration via django-allauth/invitations
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "rest_user_details"
ACCOUNT_LOGIN_ON_PASSWORD_RESET = True
ACCOUNT_EMAIL_REQUIRED = False
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USERNAME_BLACKLIST = [
    "about",
    "access",
    "account",
    "accounts",
    "add",
    "address",
    "adm",
    "admin",
    "administration",
    "adult",
    "advertising",
    "affiliate",
    "affiliates",
    "ajax",
    "analytics",
    "android",
    "anon",
    "anonymous",
    "api",
    "app",
    "apps",
    "archive",
    "atom",
    "auth",
    "authentication",
    "avatar",
    "backup",
    "banner",
    "banners",
    "bin",
    "billing",
    "blog",
    "blogs",
    "board",
    "bot",
    "bots",
    "business",
    "chat",
    "cache",
    "cadastro",
    "calendar",
    "campaign",
    "careers",
    "cgi",
    "client",
    "cliente",
    "code",
    "comercial",
    "compare",
    "config",
    "connect",
    "contact",
    "contest",
    "create",
    "code",
    "compras",
    "css",
    "dashboard",
    "data",
    "db",
    "design",
    "delete",
    "demo",
    "design",
    "designer",
    "dev",
    "devel",
    "dir",
    "directory",
    "doc",
    "docs",
    "domain",
    "download",
    "downloads",
    "edit",
    "editor",
    "email",
    "ecommerce",
    "forum",
    "forums",
    "faq",
    "favorite",
    "feed",
    "feedback",
    "flog",
    "follow",
    "file",
    "files",
    "free",
    "ftp",
    "gadget",
    "gadgets",
    "games",
    "guest",
    "group",
    "groups",
    "help",
    "home",
    "homepage",
    "host",
    "hosting",
    "hostname",
    "html",
    "http",
    "httpd",
    "https",
    "hpg",
    "info",
    "information",
    "image",
    "img",
    "images",
    "imap",
    "index",
    "invite",
    "intranet",
    "indice",
    "ipad",
    "iphone",
    "irc",
    "java",
    "javascript",
    "job",
    "jobs",
    "js",
    "knowledgebase",
    "log",
    "login",
    "logs",
    "logout",
    "list",
    "lists",
    "mail",
    "mail1",
    "mail2",
    "mail3",
    "mail4",
    "mail5",
    "mailer",
    "mailing",
    "mx",
    "manager",
    "marketing",
    "master",
    "me",
    "media",
    "message",
    "microblog",
    "microblogs",
    "mine",
    "mp3",
    "msg",
    "msn",
    "mysql",
    "messenger",
    "mob",
    "mobile",
    "movie",
    "movies",
    "music",
    "musicas",
    "my",
    "name",
    "named",
    "net",
    "network",
    "new",
    "news",
    "newsletter",
    "nick",
    "nickname",
    "notes",
    "noticias",
    "ns",
    "ns1",
    "ns2",
    "ns3",
    "ns4",
    "old",
    "online",
    "operator",
    "order",
    "orders",
    "page",
    "pager",
    "pages",
    "panel",
    "password",
    "perl",
    "pic",
    "pics",
    "photo",
    "photos",
    "photoalbum",
    "php",
    "plugin",
    "plugins",
    "pop",
    "pop3",
    "post",
    "postmaster",
    "postfix",
    "posts",
    "profile",
    "project",
    "projects",
    "promo",
    "pub",
    "public",
    "python",
    "random",
    "register",
    "registration",
    "root",
    "ruby",
    "rss",
    "sale",
    "sales",
    "sample",
    "samples",
    "script",
    "scripts",
    "secure",
    "send",
    "service",
    "shop",
    "sql",
    "signup",
    "signin",
    "search",
    "security",
    "settings",
    "setting",
    "setup",
    "site",
    "sites",
    "sitemap",
    "smtp",
    "soporte",
    "ssh",
    "stage",
    "staging",
    "start",
    "subscribe",
    "subdomain",
    "suporte",
    "support",
    "stat",
    "static",
    "stats",
    "status",
    "store",
    "stores",
    "system",
    "tablet",
    "tablets",
    "tech",
    "telnet",
    "test",
    "test1",
    "test2",
    "test3",
    "teste",
    "tests",
    "theme",
    "themes",
    "tmp",
    "todo",
    "task",
    "tasks",
    "tools",
    "tv",
    "talk",
    "update",
    "upload",
    "url",
    "user",
    "username",
    "usuario",
    "usage",
    "vendas",
    "video",
    "videos",
    "visitor",
    "win",
    "ww",
    "www",
    "www1",
    "www2",
    "www3",
    "www4",
    "www5",
    "www6",
    "www7",
    "wwww",
    "wws",
    "wwws",
    "web",
    "webmail",
    "website",
    "websites",
    "webmaster",
    "workshop",
    "xxx",
    "xpg",
    "you",
    "yourname",
    "yourusername",
    "yoursite",
    "yourdomain",
]

# Wallet model configuration
WALLET_MODEL = os.getenv("HUB20_WALLET_MODEL", "wallet.KeystoreAccount")

ETHEREUM_HD_WALLET_MNEMONIC = os.getenv("HUB20_ETHEREUM_HD_WALLET_MNEMONIC")
ETHEREUM_HD_WALLET_ROOT_KEY = os.getenv("HUB20_ETHEREUM_HD_WALLET_ROOT_KEY")


# Logging Configuration
LOG_FILE = os.getenv("HUB20_SITE_LOG_FILE")
LOG_LEVEL = os.getenv("HUB20_LOG_LEVEL", "DEBUG" if DEBUG else "INFO")


LOGGING_HANDLERS = {
    "null": {"level": "DEBUG", "class": "logging.NullHandler"},
    "console": {"level": LOG_LEVEL, "class": "logging.StreamHandler", "formatter": "verbose"},
}

if LOG_FILE:
    LOGGING_HANDLERS["file"] = {
        "level": LOG_LEVEL,
        "class": os.getenv("HUB20_LOG_FILE_HANDLER", "logging.handlers.RotatingFileHandler"),
        "formatter": "verbose",
        "filename": LOG_FILE,
        "maxBytes": int(os.getenv("HUB20_LOG_FILE_MAX_FILE_SIZE", 16 * 1024 * 1024)),
        "backupCount": int(os.getenv("HUB20_LOG_FILE_BACKUP", 3)),
    }

LOGGING_HANDLER_METHODS = ["console", "file"] if "file" in LOGGING_HANDLERS else ["console"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": "HUB20_LOG_DISABLE_EXISTING_LOGGERS" in os.environ,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s:%(pathname)s %(process)d %(lineno)d %(message)s"
        },
        "simple": {"format": "%(levelname)s:%(module)s %(lineno)d %(message)s"},
    },
    "handlers": LOGGING_HANDLERS,
    "loggers": {
        "django": {"handlers": ["null"], "propagate": True, "level": "INFO"},
        "django.db.backends:": {
            "handlers": LOGGING_HANDLER_METHODS,
            "level": "ERROR",
            "propagate": False,
        },
        "django.request": {
            "handlers": LOGGING_HANDLER_METHODS,
            "level": "ERROR",
            "propagate": False,
        },
    },
}


for app in PROJECT_APPS:
    LOGGING["loggers"][app] = {
        "handlers": LOGGING_HANDLER_METHODS,
        "level": LOG_LEVEL,
        "propagate": False,
    }
