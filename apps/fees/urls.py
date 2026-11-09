from django.urls import path

from . import views

urlpatterns = [
    path("fees/", views.invoice_list, name="fees"),
    path("fees/invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("fees/invoices/<int:pk>/payment/", views.payment_record, name="payment_record"),
    path("fees/invoices/<int:pk>/concession/", views.concession_grant, name="concession_grant"),
    path("fees/invoices/<int:pk>/cancel/", views.invoice_cancel, name="invoice_cancel"),
    path("fees/invoices/<int:pk>/pay/", views.pay_online, name="pay_online"),
    path("fees/receipts/<int:pk>/pdf/", views.receipt_pdf, name="receipt_pdf"),
    path("fees/checkout/<int:pk>/", views.checkout, name="checkout"),
    path("fees/checkout/<int:pk>/sandbox/", views.sandbox_pay, name="sandbox_pay"),
    path("fees/checkout/<int:pk>/razorpay/", views.razorpay_callback, name="razorpay_callback"),
    path("fees/setup/", views.fee_setup, name="fee_setup"),
    path("fees/setup/<int:branch_pk>/heads/new/", views.fee_head_create, name="fee_head_create"),
    path("fees/setup/<int:branch_pk>/plans/new/", views.fee_plan_create, name="fee_plan_create"),
    path("fees/plans/<int:pk>/", views.fee_plan_edit, name="fee_plan_edit"),
    path("fees/plans/<int:pk>/issue/", views.invoices_issue, name="invoices_issue"),
    path("fees/review/", views.payment_review, name="payment_review"),
    path("fees/collections/", views.collection_report, name="collections"),
]
