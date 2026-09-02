from decimal import Decimal

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.models import Wallet
from payments.serializers import (
    CreditWalletRequestSerializer,
    CreditWalletResponseSerializer,
    WalletSerializer,
)
from payments.tasks import process_payment_event
from payments.webhook_schema import is_payment_event_payload


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer

    # `credit` isn't a model CRUD operation, so drf-spectacular has no
    # ModelSerializer to introspect for it -- @extend_schema supplies the
    # request/response shape explicitly instead of guessing.
    @extend_schema(
        summary="Credit a wallet (idempotent)",
        request=CreditWalletRequestSerializer,
        responses=CreditWalletResponseSerializer,
        examples=[
            OpenApiExample(
                "Credit 50.00",
                value={"event_id": "evt-abc-123", "amount": "50.00"},
                request_only=True,
            ),
        ],
        description=(
            "Queues an idempotent credit for this wallet. Re-posting the "
            "same event_id is safe and has no further effect -- see "
            "payments.tasks.process_payment_event."
        ),
    )
    @action(detail=True, methods=["post"])
    def credit(self, request, pk=None):
        wallet = self.get_object()
        body = CreditWalletRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        async_result = process_payment_event.delay(
            body.validated_data["event_id"],
            wallet.owner_id,
            Decimal(body.validated_data["amount"]),
        )
        return Response(
            CreditWalletResponseSerializer({"result": async_result.id}).data,
            status=202,
        )


class GatewayWebhookView(APIView):
    """
    Untyped JSON in, `process_payment_event` dispatch out. `request.data`
    is `Any` as far as the type checker is concerned -- `is_payment_event_payload`
    is what turns it back into something typed before any key is read.

    Exempted from the project-wide IsAuthenticated default: a real gateway
    webhook authenticates via a shared secret / signature header, not a
    user's JWT, since the caller is the payment gateway, not a logged-in
    user. That verification is out of scope for this demo.
    """

    permission_classes = [AllowAny]

    @extend_schema(exclude=True)  # ad-hoc webhook shape, not part of the public API surface
    def post(self, request):
        payload = request.data
        if not is_payment_event_payload(payload):
            return Response({"error": "invalid payload"}, status=status.HTTP_400_BAD_REQUEST)

        # Past this point, `payload` is narrowed to PaymentEventPayload --
        # these lookups are typed, not Any.
        async_result = process_payment_event.delay(
            payload["event_id"],
            payload["owner_id"],
            Decimal(payload["amount"]),
        )
        return Response({"task_id": async_result.id}, status=status.HTTP_202_ACCEPTED)
