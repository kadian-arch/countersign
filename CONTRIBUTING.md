# Contributing

    pip install -e .
    python -m unittest discover -s tests -t .

The tests are offline and need no keys. The page and the stress test need nothing else.

## Changing the guard

`src/countersign/guard.py` is judged by rules written separately in `src/countersign/stress.py`. A change to the guard should keep both of these clean:

    python scripts/stress_guard.py --n 20000
    python scripts/mutation_check.py

The first sends random attempted refunds and payouts through the guard and fails if any call that ran broke a rule. The second breaks the guard on purpose, one protection at a time, and fails if the stress test does not notice. A new protection should come with a new rule in `stress.py` and a new mutant in `mutants.py` that removes it.

## Style

Plain code, short comments only where the reason is not obvious, no emoji. Nothing about a particular shop goes in the code: owners, limits, suppliers and what the assistant may say live in the shop's own records.

## Keys

Use the sandbox. Never commit `.env`, a key, a token or a real address. `.env.example` lists what is needed.
