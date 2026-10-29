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


def integration_profile(definition):
    getter = getattr(definition, 'baseplate_integration', None)
    return getter() if getter else None


def integration_operations(definition, placement=None):
    """Selected holes in an integral support, recut after stock fusion."""
    specification = integration_profile(definition)
    if not specification:
        return []
    placement = placement or App.Placement()
    contract = definition.contract()
    frames = {frame.name: frame for frame in contract.frames}
    holes = {hole.name: hole for hole in contract.holes}
    result = []
    for name in specification['holes']:
        hole = holes[name]
        frame = frames[hole.frame]
        axis = placement.Rotation.multVec(App.Rotation('XYZ', *frame.rotation).multVec(App.Vector(0,0,1)))
        result.append(dict(kind='tapped' if hole.thread else 'existing_clamp_bore', integrated=True,
            interface=name, part=contract.catalog_id,
            center_mm=list(placement.multVec(App.Vector(*frame.position))), axis=list(axis),
            diameter_mm=hole.diameter_mm, depth_mm=hole.depth_mm, thread=hole.thread,
            thread_depth_mm=specification.get('thread_depth_mm'), source=specification['source'],
            source_sha256=specification.get('source_sha256')))
    return result


def fuse_integrated(plate, root, relative_to, *, recesses=None, pocket_clearance=.25):
    """Union selected fabricated supports with stock; never fuse their optics.

    Both baseplate workflows use the same support solids and selected bores.
    The reference patch must fit the blank, and its optic seat cannot be buried.
    Machined plates may pass a recess-record list to expose seats below their
    reference top. Other callers retain the strict no-buried-seat behavior.
    """
    inverse = relative_to.Placement.inverse()
    stock = plate.optimalBoundingBox()
    records, objects = [], []
    for obj in descendants(root):
        specification = integration_profile(obj.Proxy)
        if not specification:
            continue
        obj.Proxy.compute_placement()
        placement = inverse * obj.Placement
        if (placement.Rotation.multVec(App.Vector(0,0,1))-App.Vector(0,0,1)).Length > 1e-7:
            raise ValueError('Integral support must stand upright: ' + obj.Label)
        frames = {f.name:f for f in obj.Proxy.contract().frames}
        seat = placement.multVec(App.Vector(*frames[specification['seat_frame']].position))
        shape = obj.Shape.copy()
        shape.Placement = placement
        bounds = shape.optimalBoundingBox()
        if bounds.ZMin < stock.ZMin - .01:
            raise ValueError('Insufficient stock thickness for integral reference patch')
        if (bounds.XMin < stock.XMin-.01 or bounds.XMax > stock.XMax+.01
                or bounds.YMin < stock.YMin-.01 or bounds.YMax > stock.YMax+.01):
            raise ValueError('Integral support footprint lies outside plate stock')
        if seat.z < -.01:
            if recesses is None:
                raise ValueError('Integral optic seat is below plate top: ' + obj.Label)
            if seat.z <= stock.ZMin + .5:
                raise ValueError('Integral support recess leaves insufficient stock')
            pocket = Part.makeBox(bounds.XLength + 2*pocket_clearance,
                bounds.YLength + 2*pocket_clearance, stock.ZMax - seat.z + .01,
                App.Vector(bounds.XMin-pocket_clearance, bounds.YMin-pocket_clearance, seat.z))
            plate = plate.cut(pocket)
            recesses.append(dict(kind='integral_support_recess', mount=obj.Label,
                mount_object=obj.Name, assembly=obj.Parent.Label,
                depth_mm=-seat.z, clearance_mm=pocket_clearance))
        plate = plate.fuse(shape)
        if len(plate.Solids) != 1:
            raise ValueError('Integral support does not join the baseplate')
        for operation in integration_operations(obj.Proxy, placement):
            center, axis = App.Vector(*operation['center_mm']), App.Vector(*operation['axis'])
            tip = center + axis*(operation['depth_mm']+tip_height(operation['diameter_mm']))
            if abs(axis.z+1) > 1e-7 or tip.z < stock.ZMin+.5:
                raise ValueError('Integral bore leaves insufficient stock below drill tip')
            operation.update(mount=obj.Label, mount_object=obj.Name, assembly=obj.Parent.Label)
            records.append(operation)
        objects.append(obj)
        if obj.ViewObject:
            obj.ViewObject.Visibility = False
    for operation in records:
        plate = plate.cut(bore(operation))
    return plate, records, objects


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
    return Part.makeCompound([bore(op) for op in operations(definition)] +
                             [shape for _, shape in clearance_pockets(definition)])


def clearance_pockets(definition, placement=None):
    """Explicit source-measured clearance boxes, separate from mounting bores."""
    specification = profile(definition) or {}
    placement = placement or App.Placement()
    for record in specification.get('clearance_pockets', []):
        size = record['size_mm']
        if len(size) != 3 or not all(math.isfinite(v) and v > 0 for v in size):
            raise ValueError('Clearance pocket dimensions must be positive')
        shape = Part.makeBox(*size, App.Vector(*record['origin_mm']))
        shape.Placement = placement * shape.Placement
        yield dict(record, source_origin_mm=list(record['origin_mm']),
                   origin_mm=list(placement.multVec(App.Vector(*record['origin_mm']))),
                   rotation_deg=list(placement.Rotation.toEulerAngles('XYZ'))), shape


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


def plate_clearances(root, relative_to):
    inverse = relative_to.Placement.inverse()
    for obj in descendants(root):
        if obj is relative_to or not profile(obj.Proxy):
            continue
        obj.Proxy.compute_placement()
        for record, shape in clearance_pockets(obj.Proxy, inverse * obj.Placement):
            yield obj, record, shape
