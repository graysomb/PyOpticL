"""Check a computed CAD trace against schematic intent, without GUI dependencies."""

from collections import Counter
from math import atan2, degrees, isfinite


def _same_direction(first, second):
    first, second = tuple(first), tuple(second)
    first_norm = sum(x * x for x in first) ** 0.5
    second_norm = sum(x * x for x in second) ** 0.5
    if not first_norm or not second_norm:
        return False
    # Compare vectors directly: dot-product tolerances merge small reflected
    # turns into the transmitted branch and lose precision near parallel rays.
    return sum((a / first_norm - b / second_norm) ** 2 for a, b in zip(first, second)) < 1e-18


def check_trace(
    beam, objects, expected, source_reference, splitters=(), open_lengths=None, output_directions=None
):
    """Check resolved interactions (out/transmitted/reflected), not symbol port IDs."""
    object_refs = {}

    def register(obj, reference):
        if obj.Name in object_refs:
            return
        object_refs[obj.Name] = reference
        for child in getattr(obj, "Children", ()):
            register(child, reference)

    for reference, proxy in objects.items():
        register(proxy.get_object(), reference)

    def reference(obj):
        return None if obj is None else object_refs.get(obj.Name, f"unknown:{obj.Label}")

    segments = list(beam.get_object().BeamSegments)
    incoming = {}
    for segment in segments:
        if segment.EndObject is not None and reference(segment.EndObject) != reference(segment.StartObject):
            incoming[reference(segment.EndObject)] = segment.Proxy.get_global_direction()
    actual, open_segments, directed_segments = [], {}, {}
    for segment in segments:
        start = segment.StartObject
        source = source_reference if start is None else reference(start)
        target = reference(segment.EndObject)
        if start is not None and source == target:
            continue  # Internal air paths/facets belong to one schematic optic.
        port = "out"
        if source in splitters:
            incident = incoming.get(source)
            if incident is None:
                raise RuntimeError(f"Schematic trace: no incident beam found for {source}")
            port = (
                "transmitted"
                if _same_direction(incident, segment.Proxy.get_global_direction())
                else "reflected"
            )
        end = segment.EndObject
        actual.append((source, port, target))
        directed_segments[(source, port, target)] = segment.Proxy
        if end is None:
            open_segments[(source, port)] = segment.Proxy
    expected, actual = Counter(map(tuple, expected)), Counter(actual)
    missing, extra = expected - actual, actual - expected
    if missing or extra:
        messages = []
        for label, collection in (("Missing", missing), ("Unexpected", extra)):
            for (source, port, target), count in collection.items():
                messages.append(f"{label}: {source}.{port} -> {target or 'open output'} ({count})")
        raise RuntimeError(
            "Schematic trace does not match the intended connections. "
            "Adjust physical placements/distances/turns and run again.\n" + "\n".join(messages)
        )
    for key, length in (open_lengths or {}).items():
        if key not in open_segments:
            raise ValueError(f"No open beam found for {key}")
        if (
            not isinstance(length, (int, float))
            or isinstance(length, bool)
            or not isfinite(length)
            or length <= 0
        ):
            raise ValueError(f"Open beam {key}: length must be a positive finite number in mm")
    for key, length in (open_lengths or {}).items():
        segment = open_segments[key]
        if segment.distance != length:
            segment.distance = length
            segment.recompute()
    for key, angle in (output_directions or {}).items():
        if not isinstance(angle, (int, float)) or isinstance(angle, bool) or not isfinite(angle):
            raise ValueError(f"Output direction {key}: angle must be finite degrees")
        if key not in directed_segments:
            raise ValueError(f"No output beam found for {key}")
        direction = directed_segments[key].get_global_direction()
        actual_angle = degrees(atan2(direction[1], direction[0]))
        if not isfinite(actual_angle) or abs((actual_angle - angle + 180) % 360 - 180) > 1e-6:
            raise RuntimeError(f"Output direction {key}: expected {angle:g}°, traced {actual_angle:g}°")
    return True


def check_pass_trace(beam, objects, expected, source_pass, tolerance=1e-6):
    """Match native ancestry to each declared visit, including repeated optics."""
    from PyOpticL.ray_math import add, mul, norm, sub

    refs = {}

    def register(obj, reference):
        if obj.Name in refs:
            return
        refs[obj.Name] = reference
        for child in getattr(obj, "Children", ()):
            register(child, reference)

    for reference, proxy in objects.items():
        register(proxy.get_object(), reference)

    def reference(obj):
        return None if obj is None else refs.get(obj.Name, "unknown:" + obj.Label)

    segments = list(beam.get_object().BeamSegments)
    consumed = set()

    def children(segment):
        return [
            child
            for child in getattr(segment, "Children", ())
            if hasattr(getattr(child, "Proxy", None), "get_global_direction")
        ]

    def close(a, b, label):
        if norm(sub(tuple(a), tuple(b))) > tolerance:
            raise RuntimeError(f"Schematic pass trace: {label} differs from solved physical geometry")

    def consume_internal(frontier, visit_id):
        total = 0.0
        while len(frontier) == 1 and getattr(frontier[0], "InternalToComponent", False):
            segment = frontier[0]
            if segment.Name in consumed:
                raise RuntimeError("Schematic pass trace: unintended recirculation")
            consumed.add(segment.Name)
            if reference(segment.EndObject) != expected[visit_id]["component"]:
                raise RuntimeError(f"Schematic pass trace: incomplete internal passage at {visit_id}")
            total += segment.Proxy.distance
            frontier = children(segment)
        if abs(total - expected[visit_id]["internal_length"]) > tolerance:
            raise RuntimeError(f"Schematic pass trace: internal path length differs at {visit_id}")
        return frontier

    roots = [s for s in segments if s.StartObject is None]
    stack = [(source_pass, roots)]
    while stack:
        visit_id, frontier = stack.pop()
        visit = expected[visit_id]
        branches = visit["branches"]
        if len(frontier) != len(branches):
            raise RuntimeError(
                f'Schematic pass trace: {visit["reference"]} ({visit_id}) expected {len(branches)} outputs, traced {len(frontier)}'
            )
        available = list(frontier)
        for role, branch in branches.items():
            candidates = [
                s for s in available if _same_direction(s.Proxy.get_global_direction(), branch["direction"])
            ]
            if len(candidates) != 1:
                raise RuntimeError(f"Schematic pass trace: missing or ambiguous {role} at {visit_id}")
            segment = candidates[0]
            available.remove(segment)
            if segment.Name in consumed:
                raise RuntimeError("Schematic pass trace: a ray was assigned to two visits")
            consumed.add(segment.Name)
            target = expected[branch["pass"]]
            if reference(segment.EndObject) != target["component"]:
                raise RuntimeError(
                    f'Schematic pass trace: {visit["reference"]}.{role} expected {target["reference"]}, traced {reference(segment.EndObject)}'
                )
            close(segment.Proxy.get_global_position(), visit["exit"], f"{visit_id} exit")
            if segment.EndObject is None:
                segment.Proxy.distance = branch["length"]
                segment.Proxy.recompute()
            if abs(segment.Proxy.distance - branch["length"]) > tolerance:
                raise RuntimeError(f'Schematic pass trace: beam length differs on {branch["connection"]}')
            endpoint = add(
                segment.Proxy.get_global_position(),
                mul(segment.Proxy.get_global_direction(), segment.Proxy.distance),
            )
            close(endpoint, target["entry"], f'{branch["pass"]} entry')
            outputs = consume_internal(children(segment), branch["pass"])
            for output in outputs:
                close(output.Proxy.get_global_position(), target["exit"], f'{branch["pass"]} exit')
            stack.append((branch["pass"], outputs))
    if len(consumed) != len(segments):
        raise RuntimeError("Schematic pass trace: unexpected extra native beam segments")
    return True
