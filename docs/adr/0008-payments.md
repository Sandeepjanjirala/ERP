# 8. Payments: integer paise, signed webhooks, idempotent capture, gapless receipts

**Status:** Accepted, November 2026 (Phase 4)

## Context

Phase 4 takes money: cash, UPI and cheques at the school office, and online payments through a provider. Mistakes here cost real trust: a payment recorded twice, a receipt number skipped or reused, a captured payment silently dropped, or a forged "payment succeeded" message. The project must also run without a provider account, never touch real money, and stay testable offline.

## Decision

**Money is whole paise in integer columns** (`total_paise`, `amount_paise`). No floats and no rounding anywhere; screens, PDFs and CSV format rupees from paise. The API also speaks paise, as Razorpay does.

**Two providers behind one interface** (`apps/fees/gateways.py`). Razorpay is used in test mode only: settings refuse to start with a key that doesn't begin with `rzp_test_`. Without keys, the built-in **Sandbox** takes payments. It sends events in Razorpay's format, signed the same way, so a Sandbox payment runs every check a real one does.

**Only the provider's signed word creates a payment.**

- **Webhooks:** the HMAC SHA-256 of the raw body is compared in constant time. A wrong signature changes nothing.
- **Razorpay browser return:** the checkout signature proves the payment id belongs to our order. The amount, currency and status are then fetched from Razorpay, never taken from the browser.
- **The order holds what was expected.** Every capture is checked against it: provider, order id, status, amount and currency.

**Idempotent capture.** `confirm_online_payment` locks the order row. A repeated event, from a webhook retry or from the browser return and the webhook both arriving, is recognised by the provider's payment id and records nothing. A unique constraint on (gateway, payment id) backs this up.

**Never discard confirmed money.**

- An amount that differs from the order is recorded and flagged for review.
- Money that arrives after the invoice was paid at the counter, or was cancelled, is recorded with a receipt and kept as *excess* (`amount − applied`) for a refund.
- Money in another currency can't be counted as rupees. It is kept on the order, with every detail, for a person to resolve.

An invoice's `paid_paise` can never exceed its total; a database constraint enforces it.

**Gapless receipt numbers** (`MDP/2026-27/00042`) come from a per-branch, per-year counter row, locked and incremented inside the payment's transaction. A payment that rolls back gives its number back. A committed number is never reused. Only confirmed payments get one.

**Concurrency** relies on row locks (`select_for_update`) on the invoice and the order, so two cashiers, or a cashier and a webhook, can't both apply the same balance. This is tested on PostgreSQL with real threads.

**Every change is audited:** plan changes (before and after), invoices issued, concessions, cancellations, counter payments and online captures. Webhook events are attributed to the parent who started the checkout.

## Consequences

- The payment logic can be tested end to end without a network or a provider account. Razorpay is exercised against its documented formats, with HTTP mocked.
- Refunds are not built: excess money is listed for finance staff to refund outside EduNexa. Refunds, late fees, instalments and other currencies are in the backlog.
- Going live needs live keys, removal of the test-mode guard, a live check of the checkout page's Content-Security-Policy, and disabling the Sandbox. All of this is in the backlog.
- A fee plan uses the classroom's grade text until Phase 5 adds a Grade model. The migration then points each plan at the matching Grade.
