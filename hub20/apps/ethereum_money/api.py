from django.urls import path

from . import views

app_name = "ethereum_money"


urlpatterns = [
    path("", views.TokenListView.as_view(), name="token-list"),
    path("<int:chain_id>-<str:address>", views.TokenView.as_view(), name="token-detail"),
]
