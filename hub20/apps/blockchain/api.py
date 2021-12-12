from rest_framework.routers import SimpleRouter

from . import views

app_name = "blockchain"


router = SimpleRouter(trailing_slash=False)
router.register("", views.ChainViewSet, basename="chain")

urlpatterns = router.urls
