from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from payments.models import Wallet
from payments.permissions import IsWalletOwner
from payments.serializers import (
    CreditWalletRequestSerializer,
    CreditWalletResponseSerializer,
    LogoutRequestSerializer,
    MeSerializer,
    RegisterSerializer,
    WalletSerializer,
)
from payments.tasks import process_payment_event
from payments.webhook_schema import is_payment_event_payload


def _me_payload(user: User) -> dict:
    wallet = Wallet.objects.filter(owner_id=user.username).first()
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "wallet": wallet,
    }


class RegisterView(APIView):
    """
    Signup: creates the User AND a zero-balance Wallet in the same call,
    so owner_id == username is a real invariant enforced at creation time
    -- not just a convention every demo happens to follow by hand.
    """

    permission_classes = [AllowAny]

    @extend_schema(request=RegisterSerializer, responses=MeSerializer)
    def post(self, request):
        body = RegisterSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        user = User.objects.create_user(
            username=body.validated_data["username"],
            email=body.validated_data["email"],
            password=body.validated_data["password"],
            first_name=body.validated_data["first_name"],
            last_name=body.validated_data["last_name"],
        )
        Wallet.objects.create(owner_id=user.username)
        return Response(MeSerializer(_me_payload(user)).data, status=status.HTTP_201_CREATED)


class MeView(APIView):
    """Who am I, and what's my wallet -- one call instead of two."""

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(_me_payload(request.user)).data)


class LogoutView(APIView):
    """
    SimpleJWT's rotation (Q2) only blacklists a refresh token when it gets
    used to rotate. Nothing in that flow lets a user end their session on
    demand -- this does: blacklist the refresh token right now, on
    request, so it can never be used again even though its own lifetime
    hasn't expired yet.
    """

    @extend_schema(request=LogoutRequestSerializer, responses={205: None, 400: None})
    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"error": "refresh is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response({"error": "invalid or already-blacklisted token"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class WalletViewSet(viewsets.ModelViewSet):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer

    # Centralized here rather than split between this and each @action's
    # own permission_classes kwarg (DRF supports both, but only one can
    # actually be in effect per action -- this is the one that wins).
    # list/retrieve/create: merely being logged in is enough. Everything
    # that mutates or acts on an EXISTING wallet needs IsWalletOwner too.
    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy", "credit"):
            return [IsAuthenticated(), IsWalletOwner()]
        return [IsAuthenticated()]

    # owner_id is read-only on the serializer (see WalletSerializer) --
    # this is the only place it's ever set, and it's always the caller's
    # own username, never anything from the request body. Wallet.owner_id
    # is unique, so a second POST from the same user hits that constraint
    # -- caught here and turned into a normal 400, not a raw 500.
    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save(owner_id=self.request.user.username)
        except IntegrityError:
            raise serializers.ValidationError({"detail": "You already have a wallet."})

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


class MiddlewareProbeView(APIView):
    """
    Deliberately trivial -- its only job is to be the innermost point of
    the middleware chain that demo_middleware_lifecycle.py hits, so the
    view itself contributes nothing to the captured request/response
    order besides being the thing every middleware wraps around.
    """

    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def get(self, request):
        request.middleware_log.append("View: handling request")
        return Response({"ok": True})


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
