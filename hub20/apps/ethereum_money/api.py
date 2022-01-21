from rest_framework.routers import SimpleRouter

from . import views

app_name = "ethereum_money"


class TokenRouter(SimpleRouter):
    def get_lookup_regex(self, viewset, lookup_prefix=""):
        return f"{lookup_prefix}(?P<chain_id>\d+)-(?P<address>0x[0-9a-fA-F]{{40}})"


token_router = TokenRouter(trailing_slash=False)
token_router.register(r"tokens", views.TokenViewSet, basename="token")


router = SimpleRouter(trailing_slash=False)
router.register(r"tokenlists", views.TokenListViewSet, basename="tokenlist")

urlpatterns = token_router.urls + router.urls
