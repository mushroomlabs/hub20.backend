from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from . import views
from .consumers import CheckoutConsumer, SessionEventsConsumer

app_name = "hub20"


class UUIDRouter(SimpleRouter):
    lookup_value_regex = "[0-9a-f-]{36}"


router = SimpleRouter(trailing_slash=False)
router.register("checkout", views.CheckoutViewSet, basename="checkout")
router.register("payments", views.PaymentViewSet, basename="payments")
router.register("tokenlists", views.TokenListViewSet, basename="tokenlist")
router.register("stores", views.StoreViewSet, basename="store")
router.register("users", views.UserViewSet, basename="users")
router.register("my/stores", views.UserStoreViewSet, basename="user-store")
router.register("my/tokens", views.UserTokenViewSet, basename="user-token")
router.register("my/tokenlists", views.UserTokenListViewSet, basename="user-tokenlist")
router.register("my/deposits", views.DepositViewSet, basename="user-deposit")
router.register("my/transfers", views.TransferViewSet, basename="user-transfer")


checkout_router = NestedSimpleRouter(router, "checkout", lookup="checkout")
checkout_router.register("routes", views.CheckoutRoutesViewSet, basename="checkout-routes")

deposit_router = NestedSimpleRouter(router, "my/deposits", lookup="deposit")
deposit_router.register("routes", views.DepositRoutesViewSet, basename="deposit-routes")


urlpatterns = (
    [
        path("credits", views.AccountCreditEntryList.as_view(), name="credit-list"),
        path("debits", views.AccountDebitEntryList.as_view(), name="debit-list"),
        path("balances", views.TokenBalanceListView.as_view(), name="balance-list"),
        path(
            "balances/<int:chain_id>-<str:address>",
            views.TokenBalanceView.as_view(),
            name="balance-detail",
        ),
        path("accounting/report", views.AccountingReportView.as_view(), name="accounting-report"),
        path("my/settings", views.UserPreferencesView.as_view(), name="user-preferences"),
    ]
    + router.urls
    + checkout_router.urls
    + deposit_router.urls
)


consumer_patterns = [
    path("events", SessionEventsConsumer.as_asgi()),
    path("checkout/<uuid:pk>", CheckoutConsumer.as_asgi()),
]
