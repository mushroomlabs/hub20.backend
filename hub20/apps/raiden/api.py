from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("nodes", views.RaidenViewSet, basename="raiden")

nodes_router = NestedSimpleRouter(router, "nodes", lookup="raiden")
nodes_router.register("channels", views.ChannelViewSet, basename="raiden-channel")
nodes_router.register("connections", views.TokenNetworkViewSet, basename="token-network")
nodes_router.register("deposits", views.ServiceDepositViewSet, basename="service-deposit")

channel_management_router = NestedSimpleRouter(nodes_router, "channels", lookup="channel")
channel_management_router.register(
    "deposits", views.ChannelDepositViewSet, basename="raiden-channel-deposit"
)
channel_management_router.register(
    "withdrawals", views.ChannelWithdrawalViewSet, basename="raiden-channel-withdrawal"
)

urlpatterns = router.urls
urlpatterns.extend(nodes_router.urls)
urlpatterns.extend(channel_management_router.urls)
