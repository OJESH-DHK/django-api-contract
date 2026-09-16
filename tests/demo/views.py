from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Address, Customer, Subscription
from .serializers import (
    AddressSerializer,
    CustomerImportSerializer,
    CustomerSerializer,
    SubscriptionSerializer,
)


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by("public_id")
    serializer_class = CustomerSerializer
    lookup_field = "public_id"


class AddressViewSet(viewsets.ModelViewSet):
    queryset = Address.objects.all().order_by("id")
    serializer_class = AddressSerializer


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subscription.objects.all().order_by("id")
    serializer_class = SubscriptionSerializer


class CustomerImportView(APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(
        request=CustomerImportSerializer,
        responses={202: CustomerImportSerializer},
        operation_id="customers-import",
    )
    def post(self, request):
        return Response(status=202)
