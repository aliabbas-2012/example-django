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
        fields = ["id", "owner_id", "balance", "balance_cents"]

    @extend_schema_field(serializers.IntegerField)
    def get_balance_cents(self, obj: Wallet) -> int:
        return int(obj.balance * 100)


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
