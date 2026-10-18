# Countersign

[![ci](https://github.com/kadian-arch/countersign/actions/workflows/ci.yml/badge.svg)](https://github.com/kadian-arch/countersign/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)
[![PayPal](https://img.shields.io/badge/built%20on-PayPal%20REST%20sandbox-0070ba.svg)](https://developer.paypal.com)

Payment guardrails for AI agents. Countersign sits between an AI assistant and a shop's PayPal account, so a stranger's email cannot talk the agent into moving money.

Built for the PayPal AI Hackathon on the PayPal REST APIs and sandbox.

## The idea

Shops are starting to let AI agents answer customers, refund buyers and pay suppliers. Those agents read text that strangers write: customer emails, dispute messages, order notes. Countersign checks every money-moving call before it reaches PayPal, in plain code and not by asking a model whether something looks suspicious. A call is allowed, held for the owner to approve, or refused, and every attempt is written to a hash-chained audit log.

## How trust is decided

- **Identity.** A From line is only text. The receiving mail server's SPF, DKIM and DMARC result (`channel.py`) decides who really sent a message. Only a confirmed message from the owner's address is the owner. A message that fails is a stranger's whatever it claims, and anything it asks for is held.
- **Authority.** A customer can only ask for a refund on their own order. A supplier's invoice is paid only at the address on record for that supplier, for an invoice on record, on the word of a contact on record.
- **Need to know.** Lookups return nothing about orders, payments or invoices that do not belong to the sender (`tools.py`), so the assistant cannot repeat what it never saw.
- **Provenance.** Each message is tagged by the channel it arrived on, and every amount and payee is traced to where it came from. A figure that appears only in text a stranger wrote does not move money, and a stranger's own message has to actually ask for the refund or the payment.
- **Limits and approval.** The owner sets the limits. Anything above them waits for approval, and approving re-runs the guard before anything is sent. If the guard itself fails, the answer is hold.
- **Audit.** Every proposal, verdict and result is chained to the one before it. Replies are checked against that log before they leave: a sentence that states a money outcome is replaced by a line taken from the log, other people's addresses are withheld, and a promise about the shop (roasting days, delivery times, where it ships) that the owner's own knowledge does not back is removed.

The guard bounds what a stranger's text can cost the shop. It does not make a language model immune to being fooled. Refunds always go back to the original payer.

## Nothing about a shop is in the code

The owner's address, the limits, what the assistant may say about the shop, the suppliers and their contacts, and the invoices all live in the shop's own records and are edited on the Setup page or through the API. The demo shop is only seed data. Plain-English rules ("refund up to $25 on my own, ask me about anything over $300") are translated into limits by a model, shown to the owner as a difference, and applied only when the owner confirms.

## Run it

    pip install -e .
    python scripts/serve.py

Open http://127.0.0.1:8000. With PayPal sandbox credentials in `.env` (see `.env.example`) the shop on the page runs on your PayPal sandbox account and a switch in the top bar opens a private practice shop on a simulated PayPal. Without credentials only the practice shop is offered. With a model key in `.env` the assistant reads email sent from the page. Without one, everything else works.

- **The live shop.** Send the shop an email. The assistant looks things up, asks for refunds and payments through the guard, and replies. The money tiles, the owner's queue and the activity table update as it happens.
- **A day at the shop.** Real runs of a demo inbox against the PayPal sandbox, replayed email by email: what the agent did without Countersign, with it, the replies that went out, and what each cost the shop.
- **Try the guard.** Fourteen examples (honest requests, attacks, forged senders) and a form for your own. No model needed.
- **Setup.** PayPal connection status, rules, shop knowledge, suppliers and contacts, and the inbound-email webhook.
- **Security.** The test results below, read from the saved results.

Every visitor gets a private practice shop on a simulated PayPal, so nothing is shared and no account is needed. Every request typed into the practice shop is also judged by the stress test's rules, and the page shows how many got through and broke one.

### Against your own PayPal account

Create a REST app in the PayPal developer dashboard with the refund and payouts features, put its credentials, your address and an owner token in `.env`, and start the console. A fresh server gives the shop its first paid sandbox orders by itself.

    python scripts/serve.py

In the PayPal shop an allowed refund or payment really goes to PayPal and its reference appears in the activity table. Anyone can try the guard and send the assistant email there, but changing settings or approving a held action needs the `OWNER_TOKEN` from `.env`. Inbound email arrives at `POST /api/inbound`, which is where a mail provider's inbound-email webhook points; each message carries the receiving server's Authentication-Results header. `--sim` runs practice shops only and `--live` the PayPal shop only.

### The shop's mailbox

With `MAIL_USER` and `MAIL_PASSWORD` in `.env` (for Gmail, an app password) the PayPal shop reads real mail. New messages are read every 20 seconds, handled by the assistant, and the reply is emailed back in the same thread. Who sent a message comes from the Authentication-Results header written by the receiving server (`mailbox.py`), not from the From line: only the topmost header counts, and only from the expected server. A reply goes only to a sender the server confirmed, at most three an hour per sender, and mail from robots and mailing lists is skipped so two assistants cannot answer each other forever. Use a mailbox made for the shop. Messages typed into the page go through the same path, without the email.

### PayPal webhooks

On the PayPal shop the server also listens to PayPal (`POST /api/paypal/webhook`). Run `python scripts/register_webhook.py` once the server is reachable at an https address (`PUBLIC_URL`), and put the id it prints in `PAYPAL_WEBHOOK_ID`. Nothing PayPal sends is believed until PayPal itself confirms the message is genuine and meant for this webhook (`verify-webhook-signature`, with the body exactly as received), and each event is handled once however often PayPal retries it.

- **Orders come from PayPal.** A captured payment the shop has no record of is read from PayPal and added as an order, so the shop is not limited to records it wrote itself. A buyer's name and order number are reduced to plain text first, since a buyer chose them.
- **Refunds made outside Countersign are noticed.** A refund made in PayPal's own dashboard is recognised as not coming from the ledger, counted against the same daily refund limit, and the owner is emailed.
- **Disputes** reach the owner as they open.
- **Payouts that do not arrive** (denied, failed, returned, blocked) put the invoice back to owed, so the books match PayPal. Held or unclaimed payouts can still arrive, so those only alert the owner.

The page shows what PayPal has reported in a "Told by PayPal" panel.

A webhook belongs to a PayPal app, not to a shop, so payments from another deployment or a test run on the same credentials reach it too. They are ignored: a payment is only learned if its invoice id starts with this shop's tag (`SHOP_TAG`, or the first part of `PUBLIC_URL`'s host when that is set, and none on a laptop), a refund or dispute only counts if it is about a payment the shop has a record of, and a payout only if the shop's own ledger sent it. Resetting the shared shop's records and audit log needs the owner token.

### PayPal's Agent Toolkit

When PayPal's `paypal-agent-toolkit` is installed (the Dockerfile and CI do it, with `--no-deps` because the package pins old agent frameworks this project does not use), the owner's assistant also gets some of its tools: transactions, disputes, invoices and merchant insights to read, and accepting a dispute, sending an invoice reminder and cancelling an invoice to act (`toolkit.py`). Those tools are exactly what a stranger's email must not reach, so they are shown to the assistant only for an email from the confirmed owner, they return nothing to anyone else even if a model asks for one by name, and the ones that act have no automatic rule, so the guard holds every one until the owner approves it, and approving runs the guard again. The toolkit has no refund or payout tool; those are Countersign's own, with the full rules.

### Checked against PayPal's SDK model

The refund, order and status handling in `paypal.py` and `guard.py` was checked with the APIMatic Context Plugin against PayPal's Server SDK model, and where it could not be (payouts, disputes, webhooks) that is said plainly. The notes are in [docs/apimatic-context-plugin.md](docs/apimatic-context-plugin.md).

### Owner alerts

When the guard holds a request, the owner is emailed at the address on the Setup page: what was asked, who asked, why it was held, and a link. The link opens a page that shows the request with Approve and Refuse buttons. Opening the link changes nothing, so a mail scanner cannot approve anything, and approving runs the guard again before PayPal is called. The link is signed with the owner token for that one request and stops working after 24 hours. At most ten alert emails go out an hour, since a stranger's requests are what create holds; the rest stay in the queue on the page and go out with the next alert. Alerts need the shop mailbox and `OWNER_TOKEN`, and can be switched off on the Setup page. Set `PUBLIC_URL` to the address the server is reached at so the links point to it.

A greeting uses the name on the From line only if it is a few plain words, since that name is the sender's own claim.

### The dashboard (AG Studio)

`/dashboard` is an [AG Studio](https://www.ag-grid.com/studio/) dashboard over the shop's own records (`GET /api/analytics`): money lost and stopped, how each request ended, which rules fired, money by day, the PayPal events and every request in a grid. A custom "Verdict ribbon" widget shows the split between requests that ran, were held and were refused. A second page, Recorded runs, shows the real model runs: the same agent wired straight to PayPal and through Countersign, by inbox and by model (`GET /api/runs`). In edit mode the page has an AI assistant, which can use its own order of providers (`STUDIO_PROVIDERS`, default the shop's `LLM_PROVIDERS`). Studio runs the conversation in the browser and asks the server for one model turn at a time (`POST /api/studio/turn`, `studio.py`), so the model keys stay on the server. The assistant answers from a few plain tools over the same numbers (`dashboard/src/analyst.ts`), because Studio's own query tool has a schema the free models this project runs on cannot fill in; its agents for placing and configuring widgets stay behind it. Arguments a model gets slightly wrong, such as a bare `"data"` where the schema wants `{"id": "data"}`, are put in the shape the tool's own schema asks for. The endpoint is capped per visitor and across everyone, and its tools only read the dashboard's data: nothing in it can reach PayPal.

The dashboard is built from `dashboard/` (React, Vite) into `src/countersign/static/dashboard`, which the Dockerfile does in its own stage. For development run `npm run dev` there while the server runs on port 8000. AG Studio works without a licence key, with a watermark and console notices; set `VITE_AG_STUDIO_LICENSE` when building to remove them.

### Being a customer on the shared shop

A visitor can place a test order with their own address: it is a real paid order in the PayPal sandbox (`POST /api/orders`, a few an hour across everyone and three per address). Writing to the shop's mailbox from that address and asking for a refund then goes through the whole path: the mail server confirms the sender, the assistant finds the order they own, the guard allows the refund, PayPal makes it and the reply arrives in their inbox. Nobody else's address can reach that order.

On the shared PayPal shop other visitors' addresses are hidden (`d***@example.com`) unless the request carries the owner token in the `X-Owner-Token` header, and a form on the page cannot vouch for the owner's address: the owner writes by email or approves from the queue.

A Dockerfile is included for hosting. Put the same variables in the host's environment.

## How it was tested

**Unit tests** (offline): `python -m unittest discover -s tests -t .`

**Stress test, no model.** A model can be talked into any call, so the guard is also judged on the calls themselves. `scripts/stress_guard.py` sends written scenarios and a seeded stream of random attempted refunds and payouts through the real guard, runtime and ledger, against a simulated PayPal. Every call that actually reaches the simulated PayPal is then checked against sixteen rules written in `stress.py`, separately from the guard: no refund to someone other than the asker, none during a dispute, none above the limits, no payment to an address not on file, none without a matching unpaid invoice, none asked for by someone who is not on record for that supplier, nothing the sender never asked for, nothing from a sender the mail server could not confirm, and so on.

    python scripts/stress_guard.py --n 100000 --seed 1
    python scripts/stress_guard.py --compare          also replays the same calls with the guard off

With the guard on, six seeds of 100,000 random attempts (600,000 in all) broke none of the rules, and neither did the 660 written scenarios. About 6,900 of each 100,000 random attempts were legitimate enough to run, so the allow path is exercised and not only the refusals. With the guard switched off, the same kind of run breaks the rules 63,946 times in 100,000. All of these runs used one version of `guard.py`; `data/stress/*.json` records its hash.

**Does the stress test notice a weak guard?** `scripts/mutation_check.py` breaks the guard on purpose, one protection at a time (no sender match, no dispute check, limits lifted, no intent check, payees learned from email, anyone may ask for a payment, mail checks ignored, and so on) and checks that the stress test flags it. It does, for all thirteen variants. Two removals (learning payees from email, forgetting that an invoice is paid) are each absorbed by a second rule, which the check reports as such.

**A model as the attacker.** `scripts/red_team.py` gives a language model the shop's records and the guard's answers (allowed, held, refused, with the reasons) and asks it to get money out. It adapts from turn to turn and never sees the guard's code. Every request that runs is judged by the same rules. Visitors to the page are the same kind of test: each request is judged live and the count is shown.

    python scripts/red_team.py --model groq/openai/gpt-oss-120b --rounds 4 --turns 25

**Model runs on the sandbox.** `scripts/run_inbox.py` runs an inbox of honest and hostile emails through an agent against the real PayPal sandbox, once with the guard and once without, and `scripts/compare_runs.py` sets the results side by side. There are three inboxes (`--inbox standard|holdout|final`); the second and third were written after earlier versions of the guard and the third is kept for the end. Results so far, from earlier versions of the guard: six pairs of runs on gpt-oss-120b (Groq and Cerebras). Without Countersign the agent lost $145.50 on average on the first inbox and $214.20 on the second. With it, $0 in every run. The runs are being repeated on the current version. `scripts/export_days.py` turns the saved runs into the replays the page shows, with the sandbox account addresses replaced by made-up ones.

What these tests do not show: how a model words replies beyond the sentence patterns the reply checker matches, and how the real PayPal behaves beyond the calls this project makes. The rules the stress test judges by were written by the author of the guard, which is why the attacker model, the visitors and the published scripts matter.

## Layout

    src/countersign/
        guard.py        the rules
        channel.py      which channel a message is on, from the mail server's sender checks
        provenance.py   where each value came from
        policy.py       the owner's limits
        profile.py      the shop's settings: owner, knowledge, limits
        runtime.py      the only path from the agent to PayPal
        tools.py        refund, payout and the need-to-know lookups
        audit.py        checks replies against the ledger and the shop's knowledge before they are sent
        agent.py        reads an email, uses the tools, writes a reply
        ledger.py       every proposal, verdict and result, hash-chained
        store.py        the shop's orders, suppliers, contacts and invoices
        paypal.py       PayPal REST client and the facts the guard reads
        llm.py          chat client with retry and model fallback
        web.py          the console, the live shop and the API
        studio.py       one model turn for the dashboard's assistant, with tool arguments repaired to their schema
        sim.py          a stand-in for PayPal, so everything runs offline
        stress.py       the stress test and the rules it judges by
        mutants.py      deliberately broken guards
        redteam.py      a model plays the attacker
        inbox.py, holdout.py, final.py     the three demo inboxes
        evaluate.py, runs.py, days.py, facts.py     run results, replays and the numbers the page quotes
    dashboard/          the AG Studio dashboard (React, builds into the server's static folder)
    tests/              offline tests
    scripts/            seeding, model runs, stress test, mutation check, red team, server

## Setup

Needs Python 3.11 or newer. The page and the stress test need nothing else. The model runs need a PayPal sandbox app and a model API key.

    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -e .
    pip install --no-deps paypal-agent-toolkit==1.11.0

The toolkit is installed with `--no-deps` because it pins old versions of agent frameworks that this project does not use. Copy `.env.example` to `.env` and fill it in.

## Licence

Apache License 2.0.
