# How the APIMatic Context Plugin was used

Countersign calls PayPal's REST API directly, so every call that moves money goes through one small client with the guard in
front of it. The APIMatic Context Plugin (`context-matic`, PayPal Server SDK, language Python) was used to check that client
against PayPal's own SDK model before it was trusted, and not to generate it.

Installed with `claude plugin marketplace add apimatic/context-matic` and `claude plugin install context-matic@apimatic`, then
used through its `fetch_api`, `ask`, `endpoint_search` and `model_search` tools.

## What it was checked against

| Countersign does | Checked with the plugin | Result |
| --- | --- | --- |
| Refund a captured payment, `POST /v2/payments/captures/{id}/refund` with amount, note and an idempotency header (`paypal.py`, `refund`) | request body, headers, the `Prefer` option | matches |
| Only `COMPLETED` and `PARTIALLY_REFUNDED` captures can be refunded (`guard.REFUNDABLE`) | the capture status list | matches |
| A refund that is `COMPLETED` or `PENDING` counts as already refunded (`LiveFacts`) | the refund status list | matches |
| Create a paid sandbox order with a card payment source (`create_paid_order`) | order and purchase unit fields | matches |
| Where captures and refunds sit in an order, and which fields an order paid by card does not carry | order details model | explains why such orders arrive from a webhook with no customer email |

It also showed an option Countersign does not use yet: `invoice_id` on a refund, which would let a refund event be tied to one
the ledger made without waiting for the ledger to catch up.

## What it does not cover

The plugin's PayPal API covers Orders, Payments, Vault, Transaction Search and Subscriptions. It does not cover Payouts,
Disputes or Webhooks (including signature verification), so `send_payout`, the dispute lookups, `verify-webhook-signature` and
webhook registration are direct REST calls that could not be checked this way.

## Not adopted, and why

The SDK itself is not a dependency: the point of the project is that one small client sits behind the guard, and a second path
to PayPal through an SDK would be a second thing to guard.
