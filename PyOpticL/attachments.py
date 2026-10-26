"""Shared attachment operations for component footprints and machined plates.

Profiles select a mounting face and its attachment features. Contract holes
describe the component; these operations describe its mating plate instead.
"""
import math
import FreeCAD as App
import Part


def profile(definition):
    getter = getattr(definition, 'baseplate_profile', None)
    return getter() if getter else None


def descendants(obj):
    for child in obj.Children:
        yield child
        yield from descendants(child)


def operations(definition, placement=None):
    specification = profile(definition)
    if not specification:
        return []
    placement = placement or App.Placement()
    contract = definition.contract()
    frames = {f.name: f for f in contract.frames}
    seat = placement.multVec(App.Vector(*frames[specification['seat_frame']].position))
    axis = placement.Rotation.multVec(App.Vector(0, 0, -1))
    result = []
    for name in specification['screws'] + specification['dowels']:
        center = placement.multVec(App.Vector(*frames[name].position))
        if abs((center - seat).dot(axis)) > .01:
            raise ValueError('Attachment feature is not on selected mounting face: ' + name)
        if name in specification['screws']:
            screw = specification.get('screw', {})
            op = dict(kind='tapped', thread=screw.get('thread', 'M4 x 0.7'),
                      diameter_mm=screw.get('diameter_mm', 3.3),
                      depth_mm=screw.get('depth_mm', 10.),
                      thread_depth_mm=screw.get('thread_depth_mm', 8.))
        else:
            dowel = specification['dowel']
            op = dict(kind='dowel', diameter_mm=dowel['plate_diameter_mm'],
                      depth_mm=dowel['plate_depth_mm'], pin=dowel['pin'],
                      projection_mm=dowel['pin_projection_mm'])
            for field in ('plate_diameter_limits_mm', 'plate_depth_tolerance_mm'):
                if field in dowel:
                    op[field.removeprefix('plate_')] = dowel[field]
            if 'note' in dowel:
                op['note'] = dowel['note']
        op.update(interface=name, center_mm=list(center), axis=list(axis),
                  part=contract.part_number or contract.catalog_id,
                  source=specification['source'],
                  step_sha256=specification.get('step_sha256'),
                  drawing_sha256=specification.get('drawing_sha256'))
        result.append(op)
    return result


def tip_height(diameter):
    return diameter / 2 / math.tan(math.radians(59))


def bore(operation):
    center, axis = App.Vector(*operation['center_mm']), App.Vector(*operation['axis'])
    radius, depth = operation['diameter_mm'] / 2, operation['depth_mm']
    cylinder = Part.makeCylinder(radius, depth + .01, center - axis * .01, axis)
    tip = Part.makeCone(radius, 0, tip_height(operation['diameter_mm']), center + axis * depth, axis)
    return cylinder.fuse(tip)


def footprint(definition):
    return Part.makeCompound([bore(op) for op in operations(definition)])


def plate_attachments(root, relative_to):
    """Yield each leaf attachment once, expressed in the plate's coordinates."""
    inverse = relative_to.Placement.inverse()
    for obj in descendants(root):
        if obj is relative_to or getattr(obj.Proxy, 'object_group', None) == 'baseplate':
            continue
        if profile(obj.Proxy):
            obj.Proxy.compute_placement()
            placement = inverse * obj.Placement
            for op in operations(obj.Proxy, placement):
                yield obj, op
