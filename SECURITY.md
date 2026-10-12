# Security

Countersign exists to stop money leaving a shop when it should not, so reports about it are welcome.

## A request got past the guard

If a refund or payment ran that should have been held or refused, that is the most useful thing you can send. For the demo and the sandbox, open an issue with the "A request got past the guard" template: the message, who it came from, and what it produced. Every request typed into the hosted practice shops is judged live against the rules in `src/countersign/stress.py`, so a break there is recorded and fixed as well.

## A vulnerability in a deployment

If the problem affects a real deployment, a real PayPal account or someone's data (a way to read other people's addresses, to act as the owner, to reach the owner token or the keys), please do not open a public issue. Use GitHub's private reporting: **Security > Report a vulnerability** on this repository. Include what you did and what you saw. You can expect a first reply within a few days.

## What is and is not in scope

In scope: the guard, the channel and sender checks, the need-to-know lookups, the reply checker, the mailbox connector, the owner token and the web API.

Not in scope: the behaviour of a language model that has been talked into asking for something (the guard exists so that this costs nothing), PayPal's own services, and denial of service against the public demo.

## Secrets

Keys, tokens and the `.env` file never belong in this repository. If you find one in the history, report it privately as above.
