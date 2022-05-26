from rest_framework.routers import SimpleRouter

from . import views

app_name = "blockchain"


router = SimpleRouter(trailing_slash=False)
router.register("chains", views.ChainViewSet, basename="chain")
router.register("wallets", views.WalletViewSet, basename="wallet")

urlpatterns = router.urls
