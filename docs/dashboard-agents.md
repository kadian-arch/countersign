# The dashboard's agents

The dashboard (`/dashboard`, built from `dashboard/`) is an AG Studio app with an assistant in its edit mode. The assistant is
not one model call. It is a few agents with different jobs, and one of them exists only to check the others.

```
visitor's question
      |
      v
   Analyst ---- plain tools over the dashboard's own data (no query language, no SQL)
      |           shop_summary, group_requests, find_requests, explain_request,
      |           paypal_events, compare_runs, find_recorded_emails
      |
      |-- asked to change the dashboard? --> Page agent (places widgets) --> Widget agent (configures them)   [Studio's own]
      |
      v
   draft answer
      |
      v
   Checker (verify.ts, plain code) ---- every dollar figure and every "request N" is looked up in the data
      |                                        |
      | all found                              | something is not in the data
      v                                        v
   "Checked against the data:               one more model call: the question, the draft, what failed and
    N figures found."                       a compact copy of the data. The new answer goes through the
                                            same check and is shown only if it passes. Otherwise the reader
                                            is told which figures could not be confirmed.
```

## Why it is built this way

**Why the analyst has simple tools.** Studio's own data agent writes structured queries against a large schema. That works with
the largest paid models. The free models this project runs on get it wrong over and over, and one question used up twenty model
calls. The analyst's tools take a few plain arguments each, and a question takes about three calls.

**Why the checker is code first.** A model asked "is this answer right?" tends to say yes. The checker does not judge. It can
only say that a figure exists in the data or that it does not, so it costs no model call, it cannot be talked into agreeing,
and it is the same check every time. A model is used only after a failure, and only to write the answer again from the data.

**What the checker accepts.** An amount is accepted if the data can account for it: a single value, a total, the sum of any
grouping (by outcome, requester, reason, day, inbox, model), or an amount quoted in a reason. A "request N" must exist, and when
an amount is given with it, it must be that request's amount, lost amount or stopped amount.

**What it does not do.** It checks figures and request numbers, not wording or reasoning. A sentence can be misleading with
every figure in it correct. It also cannot check an answer about something the dashboard does not hold.

**The same idea as the shop's email agent.** There, `audit.py` checks every reply against the ledger and the shop's own
knowledge before it is sent, and the guard decides every money move in code. In both places a model proposes and plain code
decides what is allowed to be believed or done.

## Where things are

| File | What it is |
| --- | --- |
| `dashboard/src/analyst.ts` | the analyst's tools and instructions, and the harness that connects the agents |
| `dashboard/src/verify.ts` | the figures check, with its tests in `verify.test.ts` (run with `npm test` in `dashboard/`) |
| `dashboard/src/checker.ts` | the wrapper that runs the check after the analyst and writes the correction when needed |
| `dashboard/src/adapter.ts` | one model turn from the browser to the server |
| `src/countersign/studio.py` | the server side of that turn: model keys stay on the server, requests are rate limited, and tool arguments a model gets slightly wrong are put in the shape the tool's schema asks for |

## Cost

A question with a clean answer costs the analyst's calls and nothing more. A question whose answer fails the check costs one
more call. The server caps the assistant at 20 turns an hour per visitor and 80 across everyone, and a rate-limited model is
skipped at once for the next provider (`STUDIO_PROVIDERS` sets the order for the dashboard alone).
