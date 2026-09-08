# Equipment catalogue

Machine-readable equipment data — the building blocks the layout engine places
and the engines size against. See [`../PLAN.md`](../PLAN.md) §0.1 for the schema
and §3 for how it gets populated.

## Code is here, data and crawlers are not

The catalogue **schema**, the code that reads it, and a worked example live in
this repository. The collected data and the crawlers that fetch it do not.

| | Where | Why |
|---|---|---|
| Schema, readers, example | here, open source | it is our work |
| Collected vendor documents | private S3, `catalogue/<vendor>/` | not ours to redistribute |
| Source registry and crawlers | private repo `sddc-collector` | vendor access patterns and terms |
| Standards tables | private S3, `standards/` | Standards Australia copyright |

This is the same posture jCalc, Elek and Tricab take with AS/NZS 3008: the
calculator holds the tables server-side and returns results. Verified 2026-09-04
— Tricab's client-side JavaScript contains no numeric tables at all, and jCalc's
public page cites table numbers 21 times while publishing none of their contents.

It is also what makes vendor agreements workable. "We pull your data and use it,
we do not republish it" is a much easier conversation than an open repository
full of someone's catalogue, and it is verifiable: `redistribute: false` is a
field on every source and is stamped into the provenance of every object
collected.

## Getting the data

With credentials:

```bash
export SDDC_ARTIFACTS_BUCKET=...
aws s3 sync "s3://$SDDC_ARTIFACTS_BUCKET/catalogue/" ./data/
```

Without them, [`sources.example.yaml`](sources.example.yaml) shows the shape of a
source definition, and the transcribed figures already in
[`../cables/cable_catalog.json`](../cables/cable_catalog.json) and
[`../cable-tray-ezystrut/tray_catalogue.json`](../cable-tray-ezystrut/tray_catalogue.json)
are enough to run everything in this repo.

## Facts versus documents

Dimensions, ratings and load data transcribed into the catalogues are facts, and
facts are not copyrightable. The datasheet they were read from is someone's
copyright work. The first is here; the second is not, and no code reads it.
