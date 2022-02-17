from django.urls import path
from rest_framework.routers import SimpleRouter

from hub20.apps.ethereum_money.api import TokenRouter
from hub20.apps.ethereum_money.views import TokenListViewSet, UserTokenListViewSet
from hub20.apps.wallet.views import WalletViewSet

from . import views
from .consumers import CheckoutConsumer, SessionEventsConsumer

app_name = "hub20"


class UUIDRouter(SimpleRouter):
    lookup_value_regex = "[0-9a-f-]{36}"


class TransferRouter(UUIDRouter):
    lookup_field = "reference"


token_router = TokenRouter(trailing_slash=False)
token_router.register(r"tokens", views.TokenBrowserViewSet, basename="token")
token_router.register(r"my/tokens", views.UserTokenViewSet, basename="user-token")


router = SimpleRouter(trailing_slash=False)
router.register("checkout", views.CheckoutViewSet, basename="checkout")
router.register("payments", views.PaymentViewSet, basename="payments")
router.register("tokenlists", TokenListViewSet, basename="tokenlist")
router.register("stores", views.StoreViewSet, basename="store")
router.register("users", views.UserViewSet, basename="users")
router.register("wallets", WalletViewSet, basename="wallet")
router.register("my/stores", views.UserStoreViewSet, basename="user-store")
router.register("my/tokenlists", UserTokenListViewSet, basename="user-tokenlist")
router.register("my/deposits", views.DepositViewSet, basename="user-deposit")

transfer_router = TransferRouter(trailing_slash=False)
transfer_router.register("my/transfers", views.TransferViewSet, basename="user-transfer")
transfer_router.register("my/withdrawals", views.WithdrawalViewSet, basename="user-withdrawal")


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
        path("payment/orders", views.PaymentOrderListView.as_view(), name="payment-order-list"),
        path(
            "payment/order/<uuid:pk>",
            views.PaymentOrderView.as_view(),
            name="payment-order-detail",
        ),
        path("accounting/report", views.AccountingReportView.as_view(), name="accounting-report"),
        path("my/settings", views.UserPreferencesView.as_view(), name="user-preferences"),
    ]
    + router.urls
    + token_router.urls
    + transfer_router.urls
)


consumer_patterns = [
    path("events", SessionEventsConsumer.as_asgi()),
    path("checkout/<uuid:pk>", CheckoutConsumer.as_asgi()),
]
