"""Processing provider: puts the project's algorithms in the Processing Toolbox (and so in the Model Designer)."""
import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon


class VisibilityCorridorProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        from .algorithms import ALGORITHMS
        for cls in ALGORITHMS:
            self.addAlgorithm(cls())

    def id(self):
        return "visibilitycorridor"

    def name(self):
        return "Visibility Corridor"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))

    def longName(self):
        return "Visibility Corridor: radar coverage, flight visibility and radar-hidden routing"
