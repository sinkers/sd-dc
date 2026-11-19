"""Report what a model would cost to tessellate, without tessellating it.

Triangle count for an imported STEP part is floored by its face count - every
face costs at least two triangles no matter how coarse the deflection - so face
counts predict the bill well enough to plan an export against, and cost seconds
instead of minutes.

It also counts repeats. Vendor parts arrive hundreds of times over (one pipe
fitting, one rack, one bolt) and each copy differs only by placement, so a
signature over the placement-free shape says how much of the model is worth
meshing once and instancing.

    EXPORT_GLB_ARGS="--fcstd model.FCStd" freecadcmd audit.py
"""

import collections
import os
import sys

import FreeCAD

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fcstd_gui import read_gui_state, say  # noqa: E402


def main():
    import shlex
    argv = shlex.split(os.environ.get("EXPORT_GLB_ARGS", ""))
    fcstd = argv[argv.index("--fcstd") + 1]

    gui = read_gui_state(fcstd)
    doc = FreeCAD.openDocument(fcstd)

    rows = []
    for obj in doc.Objects:
        visible, _colour = gui.get(obj.Name, (True, None))
        if not visible:
            continue
        shape = getattr(obj, "Shape", None)
        if shape is None or not shape.Faces:
            continue
        box = shape.BoundBox
        rows.append((obj.Label, len(shape.Faces), round(shape.Volume, 1),
                     round(shape.Area, 1), round(box.DiagonalLength, 1)))

    say("visible solids: %d" % len(rows))
    say("total faces: %d (floor of ~%.1fM triangles)"
        % (sum(r[1] for r in rows), sum(r[1] for r in rows) * 2 / 1e6))

    # Repeats: same face count, volume, area and size means the same part.
    signatures = collections.Counter((r[1], r[2], r[3], r[4]) for r in rows)
    unique_faces = sum(sig[0] for sig in signatures)
    say("distinct shapes: %d of %d parts (%.0f%% are repeats)"
        % (len(signatures), len(rows), 100.0 * (1 - len(signatures) / len(rows))))
    say("faces if instanced: %d (floor of ~%.1fM triangles)"
        % (unique_faces, unique_faces * 2 / 1e6))

    say("")
    say("most repeated shapes:")
    by_cost = sorted(signatures.items(), key=lambda kv: -kv[0][0] * kv[1])
    labels = {}
    for r in rows:
        labels.setdefault((r[1], r[2], r[3], r[4]), r[0])
    for sig, count in by_cost[:15]:
        say("  %5d x %6d faces = %8d  %s"
            % (count, sig[0], count * sig[0], labels[sig][:60]))

    say("")
    say("size distribution of parts (bbox diagonal):")
    buckets = [(0, 100), (100, 300), (300, 1000), (1000, 3000), (3000, 1e12)]
    for low, high in buckets:
        sel = [r for r in rows if low <= r[4] < high]
        say("  %6.0f-%-8.0f mm: %5d parts, %8d faces"
            % (low, high, len(sel), sum(r[1] for r in sel)))
    return 0


main()
