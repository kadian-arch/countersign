# Changelog

## Unreleased

- PayPal Agent Toolkit tools for the owner's assistant only: reads return nothing to anyone else, actions are held until the owner approves.
- A shop tag keeps other deployments' and test runs' payments out of a shop's records, and refunds, disputes and payouts only count if they are about something the shop has a record of.
- Resetting the shared shop needs the owner token.
- Times in the activity table are shown in the viewer's own time zone, and the Setup page shows whether the last owner email was sent.
- Odd spacing characters and stray ellipses in a model's reply are repaired before the email goes out.
- A short "four things to try" guide at the top of the live shop.
- Site icon and a share image for links (`scripts/make_brand.py` redraws them); the page tells chat and social sites where it is served from.
- A model key alone is enough for Cerebras and Groq (default model names), and the server log says which of the model, mailbox, alerts and webhook are on.
- Model runs are stamped with the version of the guard, checker, lookups, loss counting and prompt, and only matching runs are counted.
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
