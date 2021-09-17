from typing import Callable

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import TemplateView
from rest_auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetView,
    UserDetailsView,
)
from rest_framework.schemas import get_schema_view

from hub20.apps.core.api import urlpatterns as core_urlpatterns

from .views import IndexView


def make_auth_view(url_path: str, view_class, view_name: str) -> Callable:
    return path(url_path, view_class.as_view(), name=view_name)


urlpatterns = [
    # URLs that do not require a session or valid token
    make_auth_view("accounts/password/reset", PasswordResetView, "rest_password_reset"),
    make_auth_view(
        "accounts/password/confirm",
        PasswordResetConfirmView,
        "rest_password_reset_confirm",
    ),
    make_auth_view("accounts/password/change", PasswordChangeView, "rest_password_change"),
    make_auth_view("accounts/user", UserDetailsView, "rest_user_details"),
    make_auth_view("session/login", LoginView, "rest_login"),
    make_auth_view("session/logout", LogoutView, "rest_logout"),
    path("", IndexView.as_view(), name="index"),
    path("register/", include("rest_auth.registration.urls")),
    path("tokens/", include("hub20.apps.ethereum_money.api", namespace="ethereum_money")),
    path("raiden/", include("hub20.apps.raiden.api")),
]

urlpatterns.extend(core_urlpatterns)

if settings.SERVE_OPENAPI_URLS:
    urlpatterns.extend(
        [
            path(
                "docs",
                TemplateView.as_view(
                    template_name="swagger-ui.html", extra_context={"schema_url": "openapi-schema"}
                ),
                name="swagger-ui",
            ),
            path(
                "openapi",
                get_schema_view(
                    title="Hub20", description="REST API - Description", version="1.0.0"
                ),
                name="openapi-schema",
            ),
        ]
    )

urlpatterns.extend(static(settings.STATIC_URL, document_root=settings.STATIC_ROOT))
