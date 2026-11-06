from django.urls import path

from . import views

urlpatterns = [
    path(
        "payments/webhook/<str:gateway>/",
        views.PaymentWebhookView.as_view(),
        name="api-payment-webhook",
    ),
]
