from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Category, Product
from .serializers import CategorySerializer, PriceImportSerializer, ProductSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_field = "slug"


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductSerializer
    lookup_field = "sku"


class PriceImportView(APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(
        operation_id="products-import-prices",
        request=PriceImportSerializer,
        responses={202: PriceImportSerializer},
        tags=["products"],
    )
    def post(self, request):
        return Response(status=202)
