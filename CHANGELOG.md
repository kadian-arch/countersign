# Changelog

## Unreleased

- Fixed: the ledger check sent its dates with a bare "+", which a web address reads as a space, so PayPal refused the search with a 400. The dates are now encoded, and when PayPal refuses for another reason its own words are shown.
- The dashboard has a search box (a custom widget) on both pages, and the filter buttons have room to show their choices.
- The Setup page is in plainer words: the PayPal connection says what the app may do (refund, pay suppliers) with the technical permission list folded away, the ledger check and the webhook are explained without jargon.

## 0.2.0

The shop became a hosted product with a dashboard, PayPal webhooks and owner alerts, and the proof was rebuilt so that only
runs made with the current guard are counted.

### The dashboard (AG Studio)

- A dashboard at `/dashboard` with two pages: the live shop (money lost and stopped, how each request ended, which rules fired, money by day, every request) and Recorded runs (the real model runs, with and without Countersign, by inbox and by model, and every email in a grid). A custom verdict ribbon widget, a dark theme that matches the site, button filters, a Refresh button and a branded loading screen.
- It fits any screen: phones stack the widgets, tablets get the whole page, wide screens add the builder, and it re-fits when a window is resized or a device is turned. Its files are sent compressed and cached.
- An assistant in edit mode answers questions about both pages through `POST /api/studio/turn`, which keeps the model keys on the server, is rate limited, and repairs tool arguments a model gets slightly wrong. It answers from a few plain tools because Studio's own query tool was too complex for the free models this project runs on.
- A checker agent looks every dollar figure and "request N" in an answer up in the data in plain code (`verify.ts`, 7 tests run in CI). A clean answer gets a one-line note and no extra model call; a failed one gets one rewrite from the data, shown only if it passes the same check. Design and limits in `docs/dashboard-agents.md`.
- `STUDIO_PROVIDERS` gives the assistant its own order of model providers. A model call made for someone waiting at a screen moves to the next model at once when one is rate limited.
- `/api/analytics` hides other visitors' addresses on the shared shop, and `GET /api/runs` serves the recorded runs as one flat table.

### PayPal

- Webhooks, verified with PayPal and handled once. The shop learns orders from captured payments, notices refunds made outside Countersign and counts them against the daily limit, tells the owner about disputes and reversals, and puts an invoice back to owed when PayPal denies a payout. A "Told by PayPal" panel on the page. The webhook can be registered from the Setup page (owner token needed) and the id is remembered.
- A ledger check: `GET /api/reconcile` and a Setup button compare every refund Countersign made with PayPal's Transaction Search for the last 30 days, and say which refunds PayPal does not show and which it shows that the ledger never made. Nothing newer than three hours is judged. The request shape was checked with the APIMatic Context Plugin (`docs/apimatic-context-plugin.md`).
- PayPal Agent Toolkit tools for the owner's assistant only: the reads return nothing to anyone else, and the actions are held until the owner approves.
- A shop tag keeps other deployments' and test runs' payments out of a shop's records, and refunds, disputes and payouts only count if they are about something the shop has a record of.

### Owner alerts and email

- When a request is held the owner is emailed what it is, who asked and why, with a signed link to a page that approves or refuses it. Opening the link changes nothing, and approving runs the guard again. At most ten alert emails go out an hour.
- Emails and the approval page take the site's look: a dark card, the check-mark ring, a stamp (NEEDS YOU, ALERT, FYI) and brand colours, with a plain-text version as well.
- Odd spacing characters and stray ellipses in a model's reply are repaired before the email goes out (`tidy.py`, general rules, not one case).

### The shop and the page

- A "Start here: five minutes" walkthrough at the top of the README, written for any reader, with an order to read the code in and what the project does not claim.
- A short "four things to try" guide at the top of the live shop, a site icon and a share image for links, times shown in the viewer's own time zone, and the Setup page shows whether the last owner email was sent.
- The shared shop sets itself up again when it is full of visitors' orders or held requests (at most once every six hours), so it keeps working with no one watching. Resetting it by hand needs the owner token.
- The assistant's prompt in the live shop adds a greeting line. The prompt the recorded runs were measured with is unchanged and pinned by a test.

### Models and runs

- Model runs are stamped with the version of the guard, checker, lookups, loss counting and prompt, and only matching runs are counted. A model key alone is enough for Cerebras and Groq (default model names), and the server log says which of the model, mailbox, alerts and webhook are on.
- A note after a value in `.env` (`KEY=value  # note`) is no longer read as part of the value, and a stray mark after a provider name in `LLM_PROVIDERS` no longer drops the provider.

### Fixed

- The Dashboard link in the nav made the page's nav script throw, which left the shop's dropdowns and the recorded days empty. A test now checks the nav.

### Project

- CI runs on a pinned Ubuntu image and now also builds and tests the dashboard. 342 tests, a stress test, a mutation check, a Docker build and a secret scan.

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
