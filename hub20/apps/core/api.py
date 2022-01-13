from django.urls import path
from rest_framework.routers import SimpleRouter

from hub20.apps.ethereum_money.views import UserTokenListViewSet

from . import views
from .consumers import CheckoutConsumer, SessionEventsConsumer

app_name = "hub20"


router = SimpleRouter(trailing_slash=False)
router.register("checkout", views.CheckoutViewSet, basename="checkout")
router.register("payments", views.PaymentViewSet, basename="payments")
router.register("stores", views.StoreViewSet, basename="store")
router.register("users", views.UserViewSet, basename="users")
router.register(
    "accounting/wallets", views.BalanceSheetWalletViewSet, basename="accounting-wallets"
)
router.register("my/stores", views.UserStoreViewSet, basename="user-store")
router.register("my/tokenlists", UserTokenListViewSet, basename="user-tokenlist")

urlpatterns = [
    path("credits", views.AccountCreditEntryList.as_view(), name="credit-list"),
    path("debits", views.AccountDebitEntryList.as_view(), name="debit-list"),
    path("balances", views.TokenBalanceListView.as_view(), name="balance-list"),
    path(
        "balances/<int:chain_id>-<str:address>",
        views.TokenBalanceView.as_view(),
        name="balance-detail",
    ),
    path("deposits", views.DepositListView.as_view(), name="deposit-list"),
    path("deposit/<uuid:pk>", views.DepositView.as_view(), name="deposit-detail"),
    path("payment/orders", views.PaymentOrderListView.as_view(), name="payment-order-list"),
    path("payment/order/<uuid:pk>", views.PaymentOrderView.as_view(), name="payment-order-detail"),
    path("transfers", views.TransferListView.as_view(), name="transfer-list"),
    path("transfers/transfer/<int:pk>", views.TransferView.as_view(), name="transfer-detail"),
    path("accounting/report", views.AccountingReportView.as_view(), name="accounting-report"),
] + router.urls


consumer_patterns = [
    path("events", SessionEventsConsumer.as_asgi()),
    path("checkout/<uuid:pk>", CheckoutConsumer.as_asgi()),
]
