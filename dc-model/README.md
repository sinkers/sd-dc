# dc-model — moved

This component now lives in its own **private** repository, `dc-model`.

It holds a training corpus that includes third-party engineering drawings from
real planning submissions. Those are published for public consultation but are
not licensed for onward redistribution, and at least one is stamped
`Confidential`. That is why it is private, and why it is not here.

Split out 2026-09-04, with its history preserved.

## What it was

A specialist model (DC-1) that reads data centre engineering text and drawings
and emits executable geometry — plus the acquisition and extraction platform
that feeds it. See `PLAN.md` §3 for how the equipment catalogue relates to it.

## What came back out

The crawler was extracted to **`sddc-collector`**, a separate public repo:
politeness, robots and Content-Signal handling, per-host rate limiting, a SQLite
frontier and a content-addressed S3 store. Generic — nothing in it knows about
data centres. `sd-dc` will use it for the catalogue crawlers in `PLAN.md` §3.

It is not a dependency of anything in this repo today. `sd-dc` is stdlib-only;
`sddc-collector` needs httpx, protego, boto3 and pyyaml, which is why it is its
own package rather than a directory here.
