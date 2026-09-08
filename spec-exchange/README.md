# spec-exchange — protocol between the standards agent and the implementation agent

Two agents work in this repository and neither can see the other's session.
This directory is the only channel. Read this file before writing anything into
it.

## Who does what

| | Standards agent | Implementation agent |
|---|---|---|
| Reads | the licensed AS/NZS copies | this repo's code |
| Writes | `ANS-*.md`, `cable-sizing/METHODOLOGY-*.md` | `ASK-*.md`, all code and tests |
| Never writes | code, tests, fixtures, data files | `ANS-*.md`, methodology documents |

**The standards agent does not modify code.** If an answer implies a code
change, say so in the answer and let the implementation side make it. This is
not territorial: the code carries verification cases that must be seen to fail
before they pass, and an answer that silently edits the thing it is checking
destroys that evidence.

**The implementation agent does not invent conventions.** If the standard is
silent, that is an `ASK`, not a judgement call. Anything decided locally is
marked `[M-rule]` in the code and listed as an open item.

## File naming

```
ASK-NNN-slug.md     a question, written by the implementation agent
ANS-NNN-slug.md     the reply, written by the standards agent, same NNN and slug
```

`NNN` is a zero-padded serial. Never edit a file after the other side has
replied to it — supersede it with a new number and say what it supersedes.
`INDEX.md` carries one line per exchange and its state.

## States

| State | Meaning |
|---|---|
| `OPEN` | ASK written, no ANS yet |
| `ANSWERED` | ANS written, not yet implemented |
| `IMPLEMENTED` | code changed, tests green, ASK closed |
| `SUPERSEDED` | replaced by a later ASK; names its replacement |

The implementation agent maintains `INDEX.md`. The standards agent may append
to it but should not rewrite existing rows.

## The rule that matters most: licensed data

`ASK-*.md` and `ANS-*.md` are **tracked in git and will be published**. They may
carry clause numbers, table numbers, column numbers, structure, conventions and
DAME's own arithmetic. They may **not** carry transcribed table values.

Anything that needs real table values goes in `spec-exchange/private/`, which is
gitignored, and the public file references it by name. If a value is needed to
make a point, give the arithmetic and cite the cell rather than reproducing the
column.

One exception, already cleared: single published figures that are facts rather
than tables — the 5 % / 7 % / 11 % voltage drop limits, the k constants, band
edges such as 15 % / 33 % / 45 %.

## What makes a good ASK

The three things that made M4 Rev B land first time, and they are wanted every
time:

1. **Conventions stated as rules**, each with its clause reference, so the code
   can carry the citation.
2. **Numeric verification cases with expected answers.** Without these an
   implementation can only be called plausible, not verified.
3. **Open items named** rather than defaulted. A recorded gap is worth more
   than a plausible number.

An ASK should also state what the implementation side already holds, so the
answer does not re-derive work that is done.

## Signalling

Neither agent watches the filesystem. After writing a file, tell Andrew; he
tells the other side. `INDEX.md` is the source of truth for what is waiting on
whom.
