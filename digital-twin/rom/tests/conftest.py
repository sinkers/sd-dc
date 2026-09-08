import sys
from pathlib import Path

# `fields/` and `ue-export/` are scripts rather than package modules, but their
# logic still deserves tests. Put the project root on the path so they import.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
