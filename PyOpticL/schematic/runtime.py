"""Check a computed CAD trace against schematic intent, without GUI dependencies."""

from collections import Counter


def _unit_dot(first, second):
    first, second = tuple(first), tuple(second)
    norm = sum(x * x for x in first) ** 0.5 * sum(x * x for x in second) ** 0.5
    return sum(a * b for a, b in zip(first, second)) / norm if norm else 0


def check_trace(beam, objects, expected, source_reference, splitters=()):
    """Raise an actionable error for missing, extra, or swapped optical branches."""
    object_refs = {proxy.get_object().Name: reference for reference, proxy in objects.items()}
    segments = list(beam.get_object().BeamSegments)
    incoming = {}
    for segment in segments:
        if segment.EndObject is not None:
            incoming[segment.EndObject.Name] = segment.Proxy.get_global_direction()
    actual = []
    for segment in segments:
        start = segment.StartObject
        reference = source_reference if start is None else object_refs.get(start.Name, f"unknown:{start.Label}")
        port = "out"
        if reference in splitters:
            incident = incoming.get(start.Name)
            if incident is None:
                raise RuntimeError(f"Schematic trace: no incident beam found for {reference}")
            port = "transmitted" if _unit_dot(incident, segment.Proxy.get_global_direction()) > 1 - 1e-6 else "reflected"
        end = segment.EndObject
        target = None if end is None else object_refs.get(end.Name, f"unknown:{end.Label}")
        actual.append((reference, port, target))
    expected, actual = Counter(map(tuple, expected)), Counter(actual)
    missing, extra = expected - actual, actual - expected
    if missing or extra:
        messages = []
        for label, collection in (("Missing", missing), ("Unexpected", extra)):
            for (source, port, target), count in collection.items():
                messages.append(f"{label}: {source}.{port} -> {target or 'open output'} ({count})")
        raise RuntimeError("Schematic trace does not match the intended connections. "
                           "Adjust physical placements/distances/turns and run again.\n" + "\n".join(messages))
    return True
