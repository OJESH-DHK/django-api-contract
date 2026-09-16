from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AddressViewSet, CustomerImportView, CustomerViewSet, SubscriptionViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("addresses", AddressViewSet, basename="address")
router.register("subscriptions", SubscriptionViewSet, basename="subscription")

urlpatterns = [
    path("api/v1/", include(router.urls)),
    path("api/v1/customers/import/", CustomerImportView.as_view(), name="customer-import"),
]
