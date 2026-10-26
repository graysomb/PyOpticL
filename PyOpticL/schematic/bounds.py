"""Lazy, cached FreeCAD bridge for schematic physical bounds."""

from dataclasses import dataclass

from PyOpticL import settings
from PyOpticL.bounds import BoundingCircleXY


@dataclass(frozen=True)
class BoundsResult:
    circle: BoundingCircleXY | None = None
    error: str | None = None


def compute_part_circle(spec):
    import FreeCAD as App
    from PyOpticL.layout import Component

    previous = App.ActiveDocument.Name if App.ActiveDocument else None
    temporary = None
    try:
        temporary = App.newDocument("SchematicBounds")
        part = Component(label="PhysicalBounds", definition=spec.instantiate())
        return part.get_xy_bounding_circle()
    finally:
        try:
            if temporary is not None:
                App.closeDocument(temporary.Name)
        finally:
            App.setActiveDocument(previous or "")


class BoundsProvider:
    def __init__(self, compute=None):
        self.compute = compute or compute_part_circle
        self.cache = {}

    def _key(self, spec):
        return (spec, settings.get_measurement_system(), settings.get_minimum_thread_engagement(),
                settings.get_default_extra_drill_depth())

    def peek(self, spec):
        return self.cache.get(self._key(spec))

    def get(self, spec):
        key = self._key(spec)
        if key not in self.cache:
            try:
                circle = self.compute(spec)
                if not isinstance(circle, BoundingCircleXY):
                    raise ValueError("Part has no physical XY bounding circle")
                self.cache[key] = BoundsResult(circle=circle)
            except Exception as error:
                self.cache[key] = BoundsResult(error=f"{type(error).__name__}: {error}")
        return self.cache[key]

    def clear(self):
        self.cache.clear()
