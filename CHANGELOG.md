# Changelog

## Unreleased

- PayPal webhooks: verified with PayPal, handled once. The shop learns orders from captured payments, notices refunds made outside Countersign and counts them against the daily limit, tells the owner about disputes, and puts an invoice back to owed when PayPal denies the payout. A "Told by PayPal" panel on the page. `scripts/register_webhook.py` registers the server's address.
- Owner alerts: when a request is held the owner is emailed what it is, who asked and why, with a signed link to a page that approves or refuses it. Opening the link changes nothing, and approving runs the guard again.
- The assistant's prompt in the live shop adds a greeting line. The prompt the recorded runs were measured with is unchanged and pinned by a test.
- CI runs on a pinned Ubuntu image.

## 0.1.0

First public version, built for the PayPal AI Hackathon.

- The guard: refunds and payments are checked by plain code and are allowed, held for the owner or refused, with every attempt written to a hash-chained audit log.
- Sender identity from the mail server's own SPF, DKIM and DMARC result, not the From line.
- Need-to-know lookups: the assistant only sees the records that belong to the person writing.
- Reply checking against the audit log and the owner's own knowledge of the shop.
- Settings for the owner's limits, shop knowledge, suppliers and their contacts, with plain-English rules shown as a difference before they apply.
- A web console on the PayPal sandbox shop and private practice shops, updating live.
- A mailbox connector: reads mail over IMAP and replies over SMTP, only to confirmed senders.
- Visitors can place a test order with their own address and ask the shop for a refund by email.
- Stress test, mutation check, a model playing the attacker, and recorded runs of three demo inboxes with and without the guard.
