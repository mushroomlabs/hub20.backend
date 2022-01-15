from typing import Callable

from dj_rest_auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetView,
    UserDetailsView,
)
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import TemplateView
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework.permissions import AllowAny

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
    make_auth_view("session/login", LoginView, "rest_login"),
    make_auth_view("session/logout", LogoutView, "rest_logout"),
    path("my/profile", UserDetailsView.as_view(), name="rest_user_details"),
    path("register/", include("dj_rest_auth.registration.urls")),
    path("networks/blockchains/", include("hub20.apps.blockchain.api", namespace="blockchain")),
    path("networks/raiden/", include("hub20.apps.raiden.api")),
    path("", IndexView.as_view(), name="index"),
]

urlpatterns.extend(core_urlpatterns)

if settings.SERVE_OPENAPI_URLS:
    schema_view = get_schema_view(
        openapi.Info(
            title="Hub20",
            description="REST API - Description",
            default_version="1.0.0",
        ),
        public=True,
        permission_classes=(AllowAny,),
    )

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
                schema_view.without_ui(),
                name="openapi-schema",
            ),
        ]
    )

urlpatterns.extend(static(settings.STATIC_URL, document_root=settings.STATIC_ROOT))
