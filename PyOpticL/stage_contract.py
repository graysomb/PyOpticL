"""Executable linear-stage metadata, independent of CAD and descriptive DOFs."""
from dataclasses import dataclass
import math
from .component_contract import Frame


@dataclass(frozen=True)
class LinearStageSpec:
    mounting_frame: Frame
    payload_frame: Frame
    axis: tuple
    limits_mm: tuple
    reference_mm: float = 0.

    def __post_init__(self):
        axis = tuple(float(v) for v in self.axis)
        if len(axis) != 3 or not all(math.isfinite(v) for v in axis):
            raise ValueError('Stage axis must have three finite coordinates')
        length = math.sqrt(sum(v*v for v in axis))
        limits = tuple(float(v) for v in self.limits_mm)
        if (length == 0 or len(limits) != 2 or not all(math.isfinite(v) for v in limits)
                or limits[0] >= limits[1] or not math.isfinite(self.reference_mm)
                or not limits[0] <= self.reference_mm <= limits[1]):
            raise ValueError('Stage needs a nonzero axis and ordered limits containing its reference')
        object.__setattr__(self, 'axis', tuple(v/length for v in axis))
        object.__setattr__(self, 'limits_mm', limits)

    def validate_travel(self, value):
        value = float(value)
        if not math.isfinite(value) or not self.limits_mm[0] <= value <= self.limits_mm[1]:
            raise ValueError(f'Travel must be within {self.limits_mm} mm')
        return value

    def payload_at(self, travel):
        delta = self.validate_travel(travel)-self.reference_mm
        return Frame(self.payload_frame.name,
                     tuple(p+delta*a for p,a in zip(self.payload_frame.position,self.axis)),
                     self.payload_frame.rotation)
