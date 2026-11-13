"""Visibility-aware corridor planner (Track 3) as a QGIS plugin.

The routing engine (corridor/, common/ and the compiled C solver) is bundled in ./engine by
qgis_plugin/build_plugin.py; it is put on sys.path here so its modules import as in the project.
"""
import os
import sys

ENGINE = os.path.join(os.path.dirname(__file__), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def classFactory(iface):
    from .plugin import VisibilityCorridorPlugin
    return VisibilityCorridorPlugin(iface)
