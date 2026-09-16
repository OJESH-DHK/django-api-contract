from django.db import models


class Customer(models.Model):
    TIER_CHOICES = [
        ("free", "Free"),
        ("pro", "Pro"),
        ("enterprise", "Enterprise"),
    ]

    public_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True, null=True)
    tier = models.CharField(max_length=16, choices=TIER_CHOICES, default="free")
    created_at = models.DateTimeField(auto_now_add=True)


class Address(models.Model):
    customer = models.ForeignKey(Customer, related_name="addresses", on_delete=models.CASCADE)
    line1 = models.CharField(max_length=200)
    city = models.CharField(max_length=80)
    country = models.CharField(max_length=2)


class Subscription(models.Model):
    customer = models.ForeignKey(Customer, related_name="subscriptions", on_delete=models.CASCADE)
    plan = models.CharField(max_length=40)
    active = models.BooleanField(default=True)
