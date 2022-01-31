from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse_lazy
from rest_framework.views import APIView

from . import VERSION


class IndexView(APIView):
    """
    Hub20 Root Endpoint. Provides links to other endpoints and informs version for clients.
    """

    permission_classes = (AllowAny,)

    def get(self, request, **kw):
        return Response(
            {
                "current_user_url": reverse_lazy("rest_user_details", request=request),
                "blockchains_url": reverse_lazy("blockchain:chain-list", request=request),
                "accounting_report_url": reverse_lazy("accounting-report", request=request),
                "tokens_url": reverse_lazy("token-list", request=request),
                "users_url": reverse_lazy("users-list", request=request),
                "version": VERSION,
            }
        )
