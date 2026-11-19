# plans — review floor plans from the FreeCAD model, as DXF

Two steps, no hand drafting:

```bash
# 1. cut the model (headless FreeCAD; or exec the script in the GUI with PLANS_ARGS set)
PLANS_ARGS='{"fcstd": "site.FCStd", "out": "plan_geometry.json", ...extract block of the config...}' \
  /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd extract_plan_geometry.py
# 2. draw the sheets
python3 make_plans.py --geometry plan_geometry.json --config sheets.json --out drawings/
```

Each sheet comes out three ways from one modelspace: `.dxf` (R2018, true mm, A3 border scaled
by the sheet's denominator, opens in BricsCAD), `.pdf` (A3 for review) and `.png`. Cut solids
are poched; things below the cut are thin grey; tags are monospace; the title block is the
DAME sheet style. The sheet config (project data, kept beside the model, not here) sets each
sheet's cut, scale, rotation, the parts it includes, layer rules, labels, dimensions and notes.
Dimension text is always the measured model distance with thousands separators.

Needs `ezdxf` and `matplotlib` (`pip install ezdxf`).
