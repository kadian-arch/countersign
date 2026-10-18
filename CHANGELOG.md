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
- An AG Studio dashboard at `/dashboard`: the shop's numbers as tiles, charts and a grid, a custom verdict ribbon widget and a dark theme that matches the site. In edit mode an AI assistant answers questions about the requests through `POST /api/studio/turn`, which keeps the model keys on the server, is rate limited, and repairs tool arguments a model gets slightly wrong.
- The dashboard has a second page, Recorded runs, built from the real model runs (`GET /api/runs`): money lost with and without Countersign by inbox and by model, how each email ended on each side, and every email in a grid. It opens first when the live shop has no requests yet. The assistant can answer questions about both pages.
- The dashboard fits any screen: phones stack the widgets, tablets get the whole page without side panels, wide screens add the builder (which needs the room), and it re-fits when a window is resized or a device is turned. It opens on the live shop, has button filters on both pages and a Refresh button, and shows a branded loading screen.
- A ledger check against PayPal: `GET /api/reconcile` and a Setup button compare every refund Countersign made with PayPal's Transaction Search for the last 30 days, say which refunds PayPal does not show and which it shows that the ledger never made, and do not judge anything newer than three hours. Request shape taken from the APIMatic Context Plugin. 13 tests.
- A "Start here: five minutes" walkthrough at the top of the README, written for any reader, with an order to read the code in and what the project does not claim.
- The PayPal webhook can be registered from the Setup page (owner token needed) and the id is remembered; `scripts/register_webhook.py` shares the same code.
- A checker agent for the dashboard's assistant. Every dollar figure and "request N" in an answer is looked up in the data by plain code (`verify.ts`, 7 tests run in CI). A clean answer gets a one-line note and costs no extra model call; a failed one gets one rewrite from the data, shown only if it passes the same check. Design and limits in `docs/dashboard-agents.md`.
- Owner emails and the approval page take the site's look: dark card, the check-mark ring, a stamp (NEEDS YOU, ALERT, FYI), brand colours, still with a plain-text version.
- `docs/apimatic-context-plugin.md` records what the APIMatic Context Plugin was used to check, and what it cannot cover.
- (earlier) The dashboard fits a phone (tiles two to a row, everything else stacked, no side panels), edit mode keeps the assistant on the left and the builder panels on the right so the page has room, and its files are sent compressed and cached.
- Fixed: the new Dashboard link in the nav made the page's nav script throw, which left the shop's dropdowns and the recorded days empty. A test now checks the nav.
- A note after a value in `.env` (`KEY=value  # note`) is no longer read as part of the value, and a stray mark after a provider name in `LLM_PROVIDERS` no longer drops the provider.
- `STUDIO_PROVIDERS` gives the dashboard's assistant its own order of model providers.
- `/api/analytics` hides other visitors' addresses on the shared shop like the rest of the page, and carries the tables the dashboard reads.
- A model call made for someone waiting at a screen moves to the next model at once when one is rate limited, instead of waiting it out.

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
