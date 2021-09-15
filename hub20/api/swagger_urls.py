from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.views.generic import TemplateView
from rest_framework.schemas import get_schema_view

from .urls import urlpatterns as api_patterns

urlpatterns = [
    path(
        "",
        TemplateView.as_view(
            template_name="swagger-ui.html", extra_context={"schema_url": "openapi-schema"}
        ),
        name="swagger-ui",
    ),
    path(
        "api",
        get_schema_view(title="Hub20", description="REST API - Description", version="1.0.0"),
        name="openapi-schema",
    ),
]
urlpatterns.extend(api_patterns)
urlpatterns.extend(static(settings.STATIC_URL, document_root=settings.STATIC_ROOT))
