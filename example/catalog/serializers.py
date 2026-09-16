from rest_framework import serializers

from .models import Category, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["slug", "name"]


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_slug = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.all(),
        source="category",
        write_only=True,
    )

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "description",
            "price",
            "status",
            "category",
            "category_slug",
            "released_on",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class PriceImportSerializer(serializers.Serializer):
    prices = serializers.FileField(help_text="CSV file with sku,price columns.")
    dry_run = serializers.BooleanField(default=True)
