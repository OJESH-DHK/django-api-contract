from rest_framework import serializers

from .models import Address, Customer, Subscription


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = ["id", "line1", "city", "country"]


class CustomerSerializer(serializers.ModelSerializer):
    addresses = AddressSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            "public_id",
            "name",
            "email",
            "phone",
            "tier",
            "addresses",
            "created_at",
        ]
        read_only_fields = ["public_id", "created_at"]


class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ["id", "customer", "plan", "active"]


class CustomerImportSerializer(serializers.Serializer):
    upload = serializers.FileField()
    dry_run = serializers.BooleanField(default=False)
