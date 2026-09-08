"""
Standalone FreeCAD RPC server startup script.
Run with: freecadcmd start_server.py
Or: freecad --no-gui -c "exec(open('start_server.py').read())"

This starts the XML-RPC server that the MCP bridge connects to.
"""
import sys
import os
from xmlrpc.server import SimpleXMLRPCServer
import threading

# Add the MCP addon to path
mcp_path = os.path.expanduser("~/.local/share/FreeCAD/Mod/FreeCADMCP")
if mcp_path not in sys.path:
    sys.path.insert(0, mcp_path)

HOST = "0.0.0.0"
PORT = 9875

print(f"Starting FreeCAD RPC server on {HOST}:{PORT}")

# Try to import and start the MCP server
try:
    # The FreeCADMCP addon typically has its own server startup
    # We'll try to import it, otherwise fall back to a basic RPC server
    from freecad_mcp_server import start_server
    start_server(host=HOST, port=PORT)
except ImportError:
    print("FreeCADMCP module not found in expected location, starting basic RPC server...")

    import FreeCAD
    import Part

    class FreeCADRPCHandler:
        def ping(self):
            return "pong"

        def list_documents(self):
            return list(FreeCAD.listDocuments().keys())

        def create_document(self, name="Unnamed"):
            doc = FreeCAD.newDocument(name)
            return doc.Name

        def get_objects(self, doc_name=None):
            if doc_name:
                doc = FreeCAD.getDocument(doc_name)
            else:
                doc = FreeCAD.ActiveDocument
            if not doc:
                return []
            return [obj.Name for obj in doc.Objects]

        def execute_code(self, code):
            """Execute arbitrary Python code in FreeCAD context"""
            exec_globals = {"FreeCAD": FreeCAD, "Part": Part}
            exec(code, exec_globals)
            return str(exec_globals.get("result", "OK"))

    server = SimpleXMLRPCServer((HOST, PORT), allow_none=True)
    server.register_instance(FreeCADRPCHandler())
    print(f"Basic RPC server running on {HOST}:{PORT}")
    server.serve_forever()
