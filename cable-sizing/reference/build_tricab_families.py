#!/usr/bin/env python3
"""Build tricab_families.json from Tricab's public product pages.

What is public and what is not, stated plainly, because this determines what
the sizing tool can honestly do with these cables:

  PUBLIC   family code, marketing name, construction description, rated
           voltage, conductor temperature rating, conductor material,
           and the product categories a family appears under.

  GATED    every per-size electrical quantity -- current-carrying capacity,
           AC/DC resistance, reactance, overall diameter, mass, bending
           radius. Tricab puts these behind a trade login ("Login to view
           full specs"), their TriCalc sizing tool behind the same login,
           and their datasheet PDFs behind a per-session token that a
           logged-out session cannot complete. Verified 2026-09-02.

So a Tricab family can be offered as a CONSTRUCTION match against a size that
our AS/NZS 3008 engine has already chosen from a catalogue that does carry
ratings. It cannot itself drive the sizing. Inventing ratings to fill the gap
would defeat the point of the exercise, so this file carries none.

Usage: python3 reference/build_tricab_families.py <dir-of-product-html> [-o out.json]
"""
import argparse
import glob
import html as htmllib
import json
import os
import re

TEMP_RE = re.compile(r'^(\d{2,3})\s*(?:&deg;|°)\s*C$', re.I)
VOLT_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*kV$', re.I)
LOW_VOLT_RE = re.compile(r'^(\d{3})\s*/\s*(\d{3})\s*V$', re.I)


def lines_of(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    body = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', ' ', raw,
                  flags=re.S | re.I)
    body = re.sub(r'<[^>]+>', '\n', body)
    out = []
    for line in body.split('\n'):
        line = htmllib.unescape(line).replace('\xa0', ' ').strip()
        if line and line != '×':
            out.append(line)
    return out, raw


def parse(path):
    lines, raw = lines_of(path)
    base = os.path.basename(path)
    slug, cond = base[:-5].rsplit('__', 1)

    voltage, temp, vi, ti = None, None, None, None
    for i, line in enumerate(lines):
        if voltage is None:
            m = VOLT_RE.match(line)
            if m:
                voltage, vi = f"{m.group(1)}/{m.group(2)} kV", i
                continue
            m = LOW_VOLT_RE.match(line)
            if m:
                voltage, vi = f"{m.group(1)}/{m.group(2)} V", i
                continue
        if temp is None:
            m = TEMP_RE.match(line)
            if m:
                temp, ti = int(m.group(1)), i
    if voltage is None and temp is None:
        return None

    # Two page layouts are in use, so the code cannot be read from a fixed
    # offset. Layout B puts a bare family code immediately above the voltage
    # ("XL" / "0.6/1kV" / "90 C" / "Flexible Rubber"); layout A puts a full
    # product name two lines above it ("BFOI BFCI Shipboard Fire Res." /
    # "Braid Power & Control" / "0.6/1kV"). Tell them apart by whether the
    # line above the voltage is a bare code token.
    anchor = vi if vi is not None else ti
    prev = lines[anchor - 1] if anchor >= 1 else ""
    after = lines[max(vi or 0, ti or 0) + 1] if (max(vi or 0, ti or 0) + 1) < len(lines) else None
    code = name = construction = None
    if re.fullmatch(r'[A-Z][A-Z0-9]{0,3}', prev.strip()):
        code, name, construction = prev.strip(), prev.strip(), after
    else:
        name = lines[anchor - 2] if anchor >= 2 else None
        construction = prev or None
        if name:
            m = re.match(r'^([A-Z][A-Z0-9]{0,3})\b', name.strip())
            if m:
                code = m.group(1)
    if construction and construction.lower().startswith("loading matched"):
        construction = None

    return {
        "slug": slug,
        "code": code,
        "name": name,
        "construction": construction,
        "voltage": voltage,
        "max_conductor_temp_c": temp,
        "conductor": "Aluminium" if cond == "alum" else "Copper",
        "url": f"https://www.tricab.com/cable/{slug}/",
        "specs_public": False,
        "specs_gated_reason": "Tricab requires a trade login for per-size specs",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("-o", "--out", default="tricab_families.json")
    a = ap.parse_args()

    fams, skipped = [], 0
    for path in sorted(glob.glob(os.path.join(a.dir, "*.html"))):
        rec = parse(path)
        if rec is None:
            skipped += 1
            continue
        fams.append(rec)

    fams.sort(key=lambda r: (r["code"] or "zz", r["conductor"]))
    doc = {
        "source": "Tricab (tricab.com), Australian region",
        "captured": "2026-09-02",
        "captured_by": "cable-sizing/reference/build_tricab_families.py",
        "scope": "PUBLIC family metadata only. No current ratings, resistances, "
                 "reactances, diameters or masses: Tricab gates all per-size "
                 "electrical data behind a trade login, so none is recorded here "
                 "rather than being guessed.",
        "usable_for": "construction and rating match against a size already "
                      "chosen from a catalogue that carries ratings",
        "not_usable_for": "driving a cable size calculation on its own",
        "families": fams,
    }
    with open(a.out, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"{len(fams)} families -> {a.out}  ({skipped} pages had no "
          f"voltage/temperature header)")
    with_code = sum(1 for f in fams if f["code"])
    print(f"  family code parsed: {with_code}/{len(fams)}")
    print(f"  copper: {sum(1 for f in fams if f['conductor']=='Copper')}  "
          f"aluminium: {sum(1 for f in fams if f['conductor']=='Aluminium')}")


if __name__ == "__main__":
    main()
