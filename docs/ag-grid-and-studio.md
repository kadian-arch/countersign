# How Countersign uses AG Studio and AG Grid

Two places use them: the dashboard at `/dashboard` (AG Studio 3.0.0) and the activity table on the main page (AG Grid Community).
Everything below can be found in the code; the file names are given so it can be checked.

## The dashboard, `dashboard/src/`

| Feature of AG Studio | What it does here | Where |
| --- | --- | --- |
| Data model with several tables | Requests, the rules that fired, recorded model runs and PayPal's own events, loaded from the server's records | `data.ts` |
| Relationship between tables | Each rule that fired is one row linked to its request, so a search or filter on the requests narrows the rules chart and the pivot too | `data.ts` (`relationships`, `reasonRows`, tested in `data.test.ts`) |
| Expression fields | "Money at risk" (a calculated column), "Share of risky money stopped" (a measure) and "Money saved" in the recorded runs, worked out by Studio's engine | `data.ts` (`expressions`) |
| Formats | Currency and percentage formats on the money fields | `data.ts` |
| Built-in widgets | Value tiles, button filters, grouped bar and column charts, a radial gauge with its own scale, a pivot table (rule by outcome) and a grid | `state.ts` |
| Custom widgets | A search box that adds a page filter, and a verdict ribbon (one bar split by outcome) that follows the filters. Each has a data mapping, a settings form and a description the assistant can read | `widgets.tsx` |
| Theming | `studioTheme.withParams` gives Studio the same colours and fonts as the site, chart palette included | `theme.ts` |
| Layouts | One state per screen size (phone, tablet, desktop), view and edit modes, panels only where there is room | `state.ts`, `App.tsx` |
| AI harness | `createAiHarness` with an analyst agent of our own (`directLlmRunner`, five plain client tools over the dashboard's data) and Studio's own page, widget, planning and data agents behind it for building | `analyst.ts` |
| A custom agent around the analyst | A checker looks every dollar figure and request number in an answer up in the data, in plain code, and only then makes one more model call if something is not found | `checker.ts`, `verify.ts`, `docs/dashboard-agents.md` |
| A model adapter | Studio runs the conversation in the browser and asks our server for one model turn at a time, so no key is ever in the page | `adapter.ts`, `src/countersign/studio.py` |
| Tool display | The assistant's tool calls show as one line in plain words ("Looked up requests, 3 found") and open to the rows the tool returned | `toolDisplay.tsx` |
| Print | "Print report" prints the dashboard on one landscape page | `App.tsx`, `style.css` |

The licence: an AG Studio licence covers Studio and its own widgets. The two custom widgets draw with plain HTML and use no AG Grid
Enterprise code. A key is set at build time with `VITE_AG_STUDIO_LICENSE`; without one Studio runs with a watermark.

## The activity table on the main page, `src/countersign/static/index.html`

AG Grid Community, themed with its Theming API in the page's own colours (it follows the light and dark switch). It has a quick
filter box, column filters on who asked, verdict, status and reason, sorting, a colour stripe by verdict, tooltips that give the full
reason, verdict and status badges drawn by cell renderers, and "Download as CSV" for the owner's records.

## Why this matters for the product

The shop owner is not a developer. The dashboard lets them ask "why was this held?" in words and then see the rows the answer came
from, and the check on the figures means the answer is not taken on trust. The same data is what the guard wrote to its audit log.
