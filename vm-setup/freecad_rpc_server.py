#!/usr/bin/env python3
"""
FreeCAD XML-RPC Server for MCP bridge.
Runs inside FreeCAD (headless via Xvfb) and exposes the RPC interface
that the freecad-mcp MCP bridge connects to.

Usage:
    freecadcmd freecad_rpc_server.py

Or with Xvfb:
    xvfb-run -a freecadcmd freecad_rpc_server.py
"""

import sys
import os
import json
import traceback
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler

# FreeCAD imports (available when run via freecadcmd)
import FreeCAD
import Part

HOST = "0.0.0.0"
PORT = 9875


class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/RPC2",)


class FreeCADRPCServer:
    """RPC server that mirrors the FreeCAD MCP add-on's interface."""

    def ping(self):
        """Health check."""
        return "pong"

    def get_version(self):
        """Get FreeCAD version info."""
        return {
            "version": FreeCAD.Version(),
            "build_type": "headless",
        }

    def list_documents(self):
        """List all open documents."""
        docs = FreeCAD.listDocuments()
        return list(docs.keys())

    def create_document(self, name="Unnamed"):
        """Create a new document."""
        doc = FreeCAD.newDocument(name)
        return {"name": doc.Name, "label": doc.Label}

    def close_document(self, name):
        """Close a document."""
        FreeCAD.closeDocument(name)
        return True

    def save_document(self, name, path=None):
        """Save a document."""
        doc = FreeCAD.getDocument(name)
        if path:
            doc.saveAs(path)
        else:
            doc.save()
        return True

    def get_objects(self, doc_name=None):
        """Get all objects in a document."""
        if doc_name:
            doc = FreeCAD.getDocument(doc_name)
        else:
            doc = FreeCAD.ActiveDocument
        if not doc:
            return []
        result = []
        for obj in doc.Objects:
            info = {
                "name": obj.Name,
                "label": obj.Label,
                "type": obj.TypeId,
            }
            if hasattr(obj, "Shape"):
                info["has_shape"] = True
                info["bounding_box"] = str(obj.Shape.BoundBox)
            result.append(info)
        return result

    def get_object(self, obj_name, doc_name=None):
        """Get details of a specific object."""
        if doc_name:
            doc = FreeCAD.getDocument(doc_name)
        else:
            doc = FreeCAD.ActiveDocument
        obj = doc.getObject(obj_name)
        if not obj:
            return None
        info = {
            "name": obj.Name,
            "label": obj.Label,
            "type": obj.TypeId,
            "properties": {},
        }
        for prop in obj.PropertiesList:
            try:
                val = getattr(obj, prop)
                info["properties"][prop] = str(val)
            except:
                pass
        return info

    def create_object(self, type_id, name, doc_name=None, properties=None):
        """Create an object in the document."""
        if doc_name:
            doc = FreeCAD.getDocument(doc_name)
        else:
            doc = FreeCAD.ActiveDocument
        if not doc:
            doc = FreeCAD.newDocument("Unnamed")

        obj = doc.addObject(type_id, name)
        if properties:
            for key, value in properties.items():
                try:
                    setattr(obj, key, value)
                except Exception as e:
                    print(f"Warning: Could not set {key}={value}: {e}")
        doc.recompute()
        return {"name": obj.Name, "type": obj.TypeId}

    def delete_object(self, obj_name, doc_name=None):
        """Delete an object from the document."""
        if doc_name:
            doc = FreeCAD.getDocument(doc_name)
        else:
            doc = FreeCAD.ActiveDocument
        doc.removeObject(obj_name)
        doc.recompute()
        return True

    def execute_code(self, code):
        """Execute arbitrary Python code in FreeCAD context."""
        exec_globals = {
            "FreeCAD": FreeCAD,
            "Part": Part,
            "result": None,
        }
        try:
            exec(code, exec_globals)
            result = exec_globals.get("result", "OK")
            return json.dumps({"status": "ok", "result": str(result)})
        except Exception as e:
            return json.dumps({
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            })

    def execute_code_async(self, code):
        """Execute code asynchronously (same as execute_code for now)."""
        return self.execute_code(code)

    def get_view(self, doc_name=None):
        """Get current view info (limited in headless mode)."""
        return {"mode": "headless", "note": "No GUI available"}

    def recompute(self, doc_name=None):
        """Recompute the document."""
        if doc_name:
            doc = FreeCAD.getDocument(doc_name)
        else:
            doc = FreeCAD.ActiveDocument
        if doc:
            doc.recompute()
            return True
        return False

    def get_parts_list(self, doc_name=None):
        """Get a parts list / BOM."""
        if doc_name:
            doc = FreeCAD.getDocument(doc_name)
        else:
            doc = FreeCAD.ActiveDocument
        if not doc:
            return []
        parts = []
        for obj in doc.Objects:
            if hasattr(obj, "Shape") and obj.Shape.Volume > 0:
                parts.append({
                    "name": obj.Name,
                    "label": obj.Label,
                    "type": obj.TypeId,
                    "volume_mm3": obj.Shape.Volume,
                    "bounding_box": str(obj.Shape.BoundBox),
                })
        return parts


def main():
    print(f"FreeCAD RPC Server starting on {HOST}:{PORT}")
    print(f"FreeCAD version: {FreeCAD.Version()}")

    server = SimpleXMLRPCServer((HOST, PORT), requestHandler=RequestHandler, allow_none=True)
    server.register_instance(FreeCADRPCServer())
    server.register_introspection_functions()

    print(f"RPC Server listening on {HOST}:{PORT}")
    print("Ready for MCP bridge connections.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
