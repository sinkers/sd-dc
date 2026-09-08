# Contributing

## The one rule

**New reference data lands `verified: false`, with a source string.**

The value of this repository is that a consumer — human or agent — can tell a
measured number from a plausible one. That only holds if provenance is a field
rather than a comment.

```json
"provenance": {
  "source_doc": "sha256:9f2a…",
  "verified": false,
  "fields_verified": ["envelope_mm", "weight_kg"]
}
```

Per field, not per record. An envelope traced off a dimensioned drawing is
trustworthy; an airflow figure lifted from marketing copy is not. One
`verified: true` on the record would launder the second as the first.

`as3008.verification_report()` prints the status of every reference table, and
the test suite refuses to let a table be marked verified while it still carries
placeholder provenance.

## Four conventions

1. **Provenance is a field.** See above.
2. **Say which numbers are quotable.** If a measurement looks publishable but is
   wrong for a reason, write the reason down next to it.
3. **Keep capture records.** When a standard or datasheet is read, record what
   was captured, what was deliberately *not* encoded and why, and what is still
   outstanding. `cable-sizing/EXTRACTED-TABLES.md` is the model.
4. **Verify by execution.** Does the script run, does STEP export, does the pipe
   route close, do the tests pass. That is what makes output trustworthy to an
   agent.

## Vendor documents

Do not commit them. Not datasheets, not brochures, not CAD. Transcribe the
figures into the catalogue JSON with a provenance block and leave the document
in the private bucket. See "Purpose and use" in the README.

## Tests

```bash
./run-tests.sh
```

`cable-sizing` and `digital-twin` have real suites. Six components have none —
`QUALITY.md` costs the gap and prioritises it. If you are refactoring one of
those, write characterisation tests first: pin current behaviour *including* the
bugs, refactor, confirm unchanged, then fix the bugs as a separate visible
change.

`piping` is the one to be careful with. 1,676 lines, no tests, geometric code
where errors are silent, and two of its five scenarios already fail.
