#!/usr/bin/env python3
"""captions.json (written by flythrough.py) -> an ffmpeg drawtext filter chain.

    python3 captions_filter.py WORK_DIR      # prints the -vf value, or nothing

Each caption's text goes to WORK_DIR/captions/NN.txt and drawtext reads it
with textfile=, so the text needs no escaping. caption_style in the site
config may set font (a font file), size (fraction of frame height), colour,
box (background opacity 0-1) and y (fraction of frame height from the top).
"""
import json
import os
import sys

DEFAULT_FONTS = ["/System/Library/Fonts/HelveticaNeue.ttc",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def esc(path):
    # drawtext option values: escape the characters its parser treats specially
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def main(work):
    src = os.path.join(work, "captions.json")
    if not os.path.exists(src):
        return ""
    with open(src) as fh:
        data = json.load(fh)
    items, style = data.get("items", []), data.get("style", {})
    if not items:
        return ""
    font = style.get("font") or next((f for f in DEFAULT_FONTS if os.path.exists(f)), None)
    size = float(style.get("size", 0.042))
    colour = style.get("colour", "white")
    box = float(style.get("box", 0.45))
    y = float(style.get("y", 0.86))
    out_dir = os.path.join(os.path.abspath(work), "captions")
    os.makedirs(out_dir, exist_ok=True)
    filters = []
    for i, c in enumerate(items):
        tf = os.path.join(out_dir, "%02d.txt" % i)
        with open(tf, "w") as fh:
            fh.write(c["text"])
        opts = ["textfile='%s'" % esc(tf), "fontsize=h*%.4f" % size, "fontcolor=%s" % colour,
                "x=(w-text_w)/2", "y=h*%.4f-text_h/2" % y,
                "enable='between(t,%.3f,%.3f)'" % (c["start_s"], c["end_s"])]
        if font:
            opts.insert(1, "fontfile='%s'" % esc(font))
        if box > 0:
            opts += ["box=1", "boxcolor=black@%.2f" % box, "boxborderw=h*0.018"]
        filters.append("drawtext=" + ":".join(opts))
    return ",".join(filters)


if __name__ == "__main__":
    print(main(sys.argv[1]))
