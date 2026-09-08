"""
Generate verification screenshots from FreeCAD model and open HTML report.

Run this INSIDE FreeCAD (or via MCP) after building the joint examples:
    exec(open('.../generate_verification_report.py').read())

Or run standalone (without FreeCAD) to just open the existing report:
    python3 generate_verification_report.py --open-only
"""

import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERIFICATION_DIR = os.path.join(BASE_DIR, "verification")
REPORT_PATH = os.path.join(VERIFICATION_DIR, "report.html")
MODEL_PATH = os.path.join(BASE_DIR, "models", "JointExamples_v2.FCStd")

os.makedirs(VERIFICATION_DIR, exist_ok=True)


def generate_screenshots():
    """Generate all verification screenshots from FreeCAD. Must run inside FreeCAD."""
    import FreeCAD
    import FreeCADGui

    # Open model if not already open
    if "JointExamples_v2" not in FreeCAD.listDocuments():
        doc = FreeCAD.openDocument(MODEL_PATH)
    else:
        doc = FreeCAD.getDocument("JointExamples_v2")

    def show_only(prefix):
        for obj in doc.Objects:
            name = obj.Name
            match = prefix in name
            if not match and obj.InList:
                match = any(prefix in p.Name for p in obj.InList)
            if hasattr(obj, 'ViewObject') and hasattr(obj.ViewObject, 'Visibility'):
                obj.ViewObject.Visibility = match

    def shot(filename):
        path = os.path.join(VERIFICATION_DIR, filename)
        FreeCADGui.ActiveDocument.ActiveView.saveImage(path, 1920, 1080, "White")
        print(f"  Saved: {filename}")

    print("Generating verification screenshots...")

    # 1. Elbow connection
    show_only("Ex1")
    FreeCADGui.ActiveDocument.ActiveView.viewIsometric()
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("01_elbow.png")

    # 2. Tee isometric
    show_only("Ex2")
    FreeCADGui.ActiveDocument.ActiveView.viewIsometric()
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("02_tee_iso.png")

    # 3. Tee top/plan view
    FreeCADGui.ActiveDocument.ActiveView.viewTop()
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("03_tee_top.png")

    # 4. Square isometric
    show_only("Sq")
    FreeCADGui.ActiveDocument.ActiveView.viewIsometric()
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("04_square_iso.png")

    # 5. Square top
    FreeCADGui.ActiveDocument.ActiveView.viewTop()
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("05_square_top.png")

    # 6. Full gallery
    for obj in doc.Objects:
        if hasattr(obj, 'ViewObject') and hasattr(obj.ViewObject, 'Visibility'):
            obj.ViewObject.Visibility = True
    FreeCADGui.ActiveDocument.ActiveView.viewIsometric()
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("06_all.png")

    print(f"\nAll screenshots in: {VERIFICATION_DIR}/")


def open_report():
    """Open the HTML report in the default browser."""
    if os.path.exists(REPORT_PATH):
        subprocess.run(["open", REPORT_PATH])
        print(f"Opened: {REPORT_PATH}")
    else:
        print(f"Report not found: {REPORT_PATH}")
        print("Generate it first by running inside FreeCAD.")


# Entry point
if __name__ == "__main__":
    if "--open-only" in sys.argv:
        open_report()
    else:
        try:
            import FreeCAD
            generate_screenshots()
            open_report()
        except ImportError:
            print("Not running inside FreeCAD. Use --open-only to view existing report.")
            open_report()
else:
    # Running inside FreeCAD via exec()
    try:
        import FreeCAD
        generate_screenshots()
        open_report()
    except Exception as e:
        print(f"Error: {e}")
        open_report()
