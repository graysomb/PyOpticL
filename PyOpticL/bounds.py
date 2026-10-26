"""Conservative physical bounds, with no CAD imports at module load time."""

from dataclasses import dataclass, field
from itertools import product
from math import hypot, isfinite


class BoundsUnavailable(ValueError):
    """A complete physical envelope cannot be calculated."""


@dataclass(frozen=True)
class BoundingCircleXY:
    radius_mm: float
    center_mm: tuple[float, float] = field(default=(0.0, 0.0), init=False)

    def __post_init__(self):
        if (not isinstance(self.radius_mm, (int, float)) or isinstance(self.radius_mm, bool) or
                not isfinite(self.radius_mm) or self.radius_mm <= 0):
            raise ValueError("Bounding circle radius must be positive and finite")

    @property
    def diameter_mm(self):
        return 2 * self.radius_mm


def component_circle_xy(component, identity, vector, include_children=True):
    """Bound original body geometry in the root's local XY plane.

    BasePlacement composes child transforms without depending on a document
    recompute, visibility, or the root's current global placement. Mesh copies
    discard display placement, which compute_shape may put on shared meshes;
    their imported model alignment is already baked into the vertex geometry.
    """
    radius = 0.0
    active = set()

    def visit(proxy, transform, descend):
        nonlocal radius
        obj = proxy.get_object()
        label = obj.Label
        key = id(proxy)
        if key in active:
            raise BoundsUnavailable(f"{label}: cyclic component assembly")
        active.add(key)
        try:
            geometries = []
            if hasattr(proxy, "mesh"):
                mesh = proxy.mesh.copy()
                if mesh.CountFacets == 0:
                    raise BoundsUnavailable(f"{label}: physical mesh is empty or missing")
                mesh.Placement = type(identity)()
                geometries.append(mesh)
            elif hasattr(proxy, "shape"):
                shapes = proxy.shape()
                geometries.extend(shapes if isinstance(shapes, list) else [shapes])
                if not geometries:
                    raise BoundsUnavailable(f"{label}: physical shape is empty")
            for geometry in geometries:
                if geometry is None or (hasattr(geometry, "isNull") and geometry.isNull()):
                    raise BoundsUnavailable(f"{label}: physical shape is empty")
                box = geometry.copy().BoundBox
                ranges = ((box.XMin, box.XMax), (box.YMin, box.YMax), (box.ZMin, box.ZMax))
                if not all(isfinite(lo) and isfinite(hi) and lo <= hi for lo, hi in ranges):
                    raise BoundsUnavailable(f"{label}: invalid physical bounding box")
                for corner in product(*ranges):
                    point = transform.multVec(vector(*corner))
                    distance = hypot(point.x, point.y)
                    if not isfinite(distance):
                        raise BoundsUnavailable(f"{label}: invalid physical placement")
                    radius = max(radius, distance)
            children = list(obj.Children)
            if not geometries and not children:
                raise BoundsUnavailable(f"{label}: no physical geometry")
            if descend:
                for child in children:
                    visit(child.Proxy, transform * child.BasePlacement, True)
        except BoundsUnavailable:
            raise
        except Exception as error:
            raise BoundsUnavailable(f"{label}: {error}") from error
        finally:
            active.remove(key)

    visit(component, identity, include_children)
    if radius <= 0:
        raise BoundsUnavailable("No physical XY extent in the requested component geometry")
    return BoundingCircleXY(radius)
