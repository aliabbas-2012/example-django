from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from payments.models import ProcessedEvent, Wallet


class WalletSerializer(serializers.ModelSerializer):
    # A plain SerializerMethodField has no type info drf-spectacular can
    # introspect (it just sees "a method that returns something"), so its
    # schema would default to a free-form string. @extend_schema_field
    # tells it the real OpenAPI type, closing that gap.
    balance_cents = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ["id", "owner_id", "balance", "balance_cents", "txn_count"]
        # Every field here is read-only. owner_id is set once, from the
        # authenticated user, in WalletViewSet.perform_create -- never
        # from client input. balance/txn_count only ever move through
        # process_payment_event (Q5) and the post_save signal (Q11)
        # respectively; letting a PATCH touch either directly would let a
        # client hand-set their own balance. See demo_auth_api.py for the
        # proof that a PATCH attempting exactly that has no effect at all.
        read_only_fields = ["owner_id", "balance", "txn_count"]

    @extend_schema_field(serializers.IntegerField)
    def get_balance_cents(self, obj: Wallet) -> int:
        return int(obj.balance * 100)


class RegisterSerializer(serializers.Serializer):
    """Request body for RegisterView -- deliberately its own serializer
    rather than a ModelSerializer on User, since "password" here is a
    write-only plaintext input, not the model's hashed password field."""

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class MeSerializer(serializers.Serializer):
    """Response body for RegisterView and MeView -- the user plus their
    wallet in one shape, so a client never has to make two calls just to
    render 'who am I and what's my balance'."""

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    wallet = WalletSerializer(read_only=True, allow_null=True)


class ProcessedEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessedEvent
        fields = ["id", "event_id", "created_at"]


class CreditWalletRequestSerializer(serializers.Serializer):
    """Request body for WalletViewSet.credit -- not tied to a model, so
    drf-spectacular can't infer it from Meta; it's introspected directly
    from these DRF fields instead."""

    event_id = serializers.CharField(max_length=128)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class CreditWalletResponseSerializer(serializers.Serializer):
    result = serializers.CharField()
