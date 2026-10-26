"""Check a computed CAD trace against schematic intent, without GUI dependencies."""

from collections import Counter
from math import isfinite


def _same_direction(first, second):
    first, second = tuple(first), tuple(second)
    first_norm = sum(x * x for x in first) ** 0.5
    second_norm = sum(x * x for x in second) ** 0.5
    if not first_norm or not second_norm:
        return False
    # Compare vectors directly: dot-product tolerances merge small reflected
    # turns into the transmitted branch and lose precision near parallel rays.
    return sum((a / first_norm - b / second_norm) ** 2 for a, b in zip(first, second)) < 1e-18


def check_trace(beam, objects, expected, source_reference, splitters=(), open_lengths=None):
    """Check resolved interactions (out/transmitted/reflected), not symbol port IDs."""
    object_refs = {proxy.get_object().Name: reference for reference, proxy in objects.items()}
    segments = list(beam.get_object().BeamSegments)
    incoming = {}
    for segment in segments:
        if segment.EndObject is not None:
            incoming[segment.EndObject.Name] = segment.Proxy.get_global_direction()
    actual, open_segments = [], {}
    for segment in segments:
        start = segment.StartObject
        reference = source_reference if start is None else object_refs.get(start.Name, f"unknown:{start.Label}")
        port = "out"
        if reference in splitters:
            incident = incoming.get(start.Name)
            if incident is None:
                raise RuntimeError(f"Schematic trace: no incident beam found for {reference}")
            port = "transmitted" if _same_direction(incident, segment.Proxy.get_global_direction()) else "reflected"
        end = segment.EndObject
        target = None if end is None else object_refs.get(end.Name, f"unknown:{end.Label}")
        actual.append((reference, port, target))
        if end is None:
            open_segments[(reference, port)] = segment.Proxy
    expected, actual = Counter(map(tuple, expected)), Counter(actual)
    missing, extra = expected - actual, actual - expected
    if missing or extra:
        messages = []
        for label, collection in (("Missing", missing), ("Unexpected", extra)):
            for (source, port, target), count in collection.items():
                messages.append(f"{label}: {source}.{port} -> {target or 'open output'} ({count})")
        raise RuntimeError("Schematic trace does not match the intended connections. "
                           "Adjust physical placements/distances/turns and run again.\n" + "\n".join(messages))
    for key, length in (open_lengths or {}).items():
        if key not in open_segments:
            raise ValueError(f"No open beam found for {key}")
        if not isinstance(length, (int, float)) or isinstance(length, bool) or not isfinite(length) or length <= 0:
            raise ValueError(f"Open beam {key}: length must be a positive finite number in mm")
    for key, length in (open_lengths or {}).items():
        segment = open_segments[key]
        if segment.distance != length:
            segment.distance = length
            segment.recompute()
    return True
