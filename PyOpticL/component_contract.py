"""Optional, inert component metadata. No FreeCAD import or motion semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math


def _vector(value, name):
    value = tuple(float(x) for x in value)
    if len(value) != 3 or not all(math.isfinite(x) for x in value):
        raise ValueError(f"{name} must contain three finite numbers")
    return value


def rotate(vector, xyz_degrees):
    """Apply fixed XYZ rotations, matching App.Rotation('XYZ', ...)."""
    x, y, z = _vector(vector, "vector")
    a, b, c = (math.radians(v) for v in _vector(xyz_degrees, "rotation"))
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    x, y = x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c)
    return (x, y, z)


@dataclass(frozen=True)
class Frame:
    """A datum expressed directly in component coordinates, in mm/degrees."""
    name: str
    position: tuple = (0, 0, 0)
    rotation: tuple = (0, 0, 0)

    def __post_init__(self):
        object.__setattr__(self, "position", _vector(self.position, "position"))
        object.__setattr__(self, "rotation", _vector(self.rotation, "rotation"))


@dataclass(frozen=True)
class Thread:
    designation: str
    gender: str
    diameter_mm: float
    pitch_mm: float

    def __post_init__(self):
        if self.gender not in ("internal", "external"):
            raise ValueError("Thread gender must be internal or external")
        if not all(math.isfinite(v) and v > 0 for v in (self.diameter_mm, self.pitch_mm)):
            raise ValueError("Thread diameter and pitch must be positive")


@dataclass(frozen=True)
class MechanicalInterface:
    name: str
    frame: str
    kind: str
    thread: Thread | None = None
    connector: str | None = None
    seating: str = ""
    engagement_mm: float | None = None


@dataclass(frozen=True)
class Hole:
    name: str
    frame: str
    diameter_mm: float
    depth_mm: float | None = None
    thread: str | None = None
    counterbore_mm: float | None = None
    source: str = ""

    def __post_init__(self):
        for value in (self.diameter_mm, self.depth_mm, self.counterbore_mm):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError("Hole dimensions must be positive")


@dataclass(frozen=True)
class DOF:
    name: str
    kind: str
    frame: str
    axis: tuple
    affects: str
    source: str
    limits: tuple | None = None

    def __post_init__(self):
        if self.kind not in ("rotation", "translation"):
            raise ValueError("DOF kind must be rotation or translation")
        axis = _vector(self.axis, "axis")
        length = math.sqrt(sum(v*v for v in axis))
        if length == 0:
            raise ValueError("DOF axis cannot be zero")
        object.__setattr__(self, "axis", tuple(v/length for v in axis))
        if self.limits is not None:
            limits = tuple(float(v) for v in self.limits)
            if len(limits) != 2 or not all(math.isfinite(v) for v in limits) or limits[0] > limits[1]:
                raise ValueError("DOF limits must be an ordered finite pair")
            object.__setattr__(self, "limits", limits)


@dataclass(frozen=True)
class Provenance:
    source: str
    status: str = "unverified"
    sha256: str | None = None
    note: str = ""

    def __post_init__(self):
        if self.status not in ("unverified", "documented", "cad_verified"):
            raise ValueError("Unknown verification status")


@dataclass(frozen=True)
class ComponentContract:
    catalog_id: str
    revision: str
    manufacturer: str
    part_number: str
    procurement: str
    frames: tuple = (Frame("origin"),)
    interfaces: tuple = ()
    holes: tuple = ()
    dofs: tuple = ()
    provenance: tuple = ()
    optical_reference: str | None = None

    def __post_init__(self):
        if self.procurement not in ("purchased", "fabricated", "assembly", "generic"):
            raise ValueError("Unknown procurement type")
        for name in ("frames", "interfaces", "holes", "dofs", "provenance"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        names = [frame.name for frame in self.frames]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate frame names")
        references = [item.frame for item in (*self.interfaces, *self.holes, *self.dofs)]
        if self.optical_reference is not None:
            references.append(self.optical_reference)
        if set(references) - set(names):
            raise ValueError("Unknown reference frame")

    def summary(self):
        return "; ".join(f"{d.name} ({d.kind}, {d.frame})" for d in self.dofs) or "Fixed after installation"

    def axes(self, assembly_rotation=(0, 0, 0)):
        frames = {f.name: f for f in self.frames}
        return {d.name: rotate(rotate(d.axis, frames[d.frame].rotation), assembly_rotation) for d in self.dofs}

    def to_dict(self):
        return {"schema_version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        if value.pop("schema_version", None) != 1:
            raise ValueError("Unsupported component contract version")
        for key, kind in (("frames", Frame), ("holes", Hole), ("dofs", DOF), ("provenance", Provenance)):
            value[key] = tuple(kind(**item) for item in value.get(key, ()))
        interfaces = []
        for item in value.get("interfaces", ()):
            item = dict(item)
            if item.get("thread") is not None:
                item["thread"] = Thread(**item["thread"])
            interfaces.append(MechanicalInterface(**item))
        value["interfaces"] = tuple(interfaces)
        return cls(**value)


def connection_check(left, right):
    """Check the mating standard only; seating and clearance need CAD evidence."""
    if left.kind != right.kind:
        return False, "Different interface kinds"
    if left.thread is not None and right.thread is not None:
        a, b = left.thread, right.thread
        if a.gender == b.gender:
            return False, "Threads have the same gender"
        if not (math.isclose(a.diameter_mm, b.diameter_mm, abs_tol=1e-6) and
                math.isclose(a.pitch_mm, b.pitch_mm, abs_tol=1e-6)):
            return False, "Thread diameter or pitch mismatch"
        return True, "Thread-compatible; seating, engagement and clearance require verification"
    if left.connector and right.connector:
        return left.connector == right.connector, "Connector comparison only; mating mechanics require verification"
    return False, "Unsupported or unspecified mating interface"
