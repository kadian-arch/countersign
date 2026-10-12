# Changelog

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
