from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("invoices", views.InvoiceViewSet, basename="api-invoice")
router.register("payments", views.PaymentViewSet, basename="api-payment")
router.register("payment-orders", views.PaymentOrderViewSet, basename="api-payment-order")
router.register("fee-heads", views.FeeHeadViewSet, basename="api-fee-head")
router.register("fee-plans", views.FeePlanViewSet, basename="api-fee-plan")

urlpatterns = [
    # Before the router, so "webhook" is never read as a payment id.
    path(
        "payments/webhook/<str:gateway>/",
        views.PaymentWebhookView.as_view(),
        name="api-payment-webhook",
    ),
    path("receipts/<int:pk>/pdf/", views.ReceiptPDFView.as_view(), name="api-receipt-pdf"),
    path("reports/collections/", views.CollectionsView.as_view(), name="api-collections"),
    path(
        "reports/collections/export/",
        views.CollectionsExportView.as_view(),
        name="api-collections-export",
    ),
    *router.urls,
]
