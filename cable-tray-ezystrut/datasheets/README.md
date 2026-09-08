# Ezystrut datasheets — not in this repo

The PDFs that were here are copyright Korvest Ltd. Their terms
(<https://www.ezystrut.com.au/legals/>) state:

> "These materials may not be copied for commercial use or distribution, nor may
> these materials be modified or reposted to other websites."

Publishing them from a public repository is exactly that, so they are not here.

## What is here instead

`../tray_catalogue.json` holds the transcribed dimensions, load and span data for
all five families. The facts in a datasheet are not the datasheet, and the
catalogue is what the code actually reads — nothing imports these PDFs.

## Getting them

Free, no login, from <https://www.ezystrut.com.au/catalogues-and-downloads/>:

| Document | Covers |
|---|---|
| EzyStrut Cable Support Quick Order Guide | the dimensional source for `tray_catalogue.json` |
| Fire Rated Catalogue | fire-rated support systems |
| Seismic Catalogue | seismic bracing |
| Mesh Cable Supports Brochure (BASOR) | mesh tray |

For the team, they are already collected to the private artifacts bucket under
`catalogue/ezystrut/`, fetched by `catalogue/crawl.py`. The STEP models that were
under `../models/step-files/` are bracket and trapeze geometry from the same
source and under the same terms.

## Open action

Korvest publish a route to remove the ambiguity: contact them for a
"Copyright Release Form". Their terms permit "private study and private use" and
require written permission otherwise, so commercial engineering use sits in a
grey area that a form would settle. Tracked in `catalogue/sources.yaml` under
`open_action`.
