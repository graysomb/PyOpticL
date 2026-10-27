"""CAD-datum-driven plate machining for the lab catalog.

Plate top is Z=0. Declared integral supports are fused from component geometry;
no automatic spacers are introduced.
Tapped holes are represented by tap-drill bores and explicit thread metadata.
"""
import json
import math
import FreeCAD as App
import Part
from PyOpticL import lab_catalog
from PyOpticL.layout import Component
from PyOpticL import attachments

PROFILES = json.loads((lab_catalog.DATA / 'baseplate_interfaces.json').read_text())


def optical_height():
    """Mirror optical axis above its documented mounting face, in mm."""
    mount = lab_catalog.VendorPart('POLARIS-K05VS2')
    frame = next(f for f in mount.contract().frames if f.name == 'mounting_face')
    return -frame.position[2]


def descendants(obj):
    for child in obj.Children:
        yield child
        yield from descendants(child)


class MachinedBaseplate:
    always_recompute_shape = True
    object_group = 'baseplate'
    object_color = (.7,.72,.75)
    apply_drilling = False  # Operations are generated explicitly below.
    part_numbers = []

    def __init__(self, layout, thickness=12.7, margin=15, pocket_clearance=.25):
        if thickness <= 10 or margin < 3 or pocket_clearance < 0:
            raise ValueError('Plate needs >10 mm thickness, >=3 mm margin and nonnegative clearance')
        self.layout = layout
        self.thickness, self.margin = thickness, margin
        self.pocket_clearance = pocket_clearance
        self.plan = {}
        self.integrated_names = []

    def _relative(self, obj):
        reference = getattr(self, '_object', self.layout.get_object())
        return reference.Placement.inverse() * obj.Placement

    def shape(self):
        hardware, fused, integrated = [], [], []
        for obj in descendants(self.layout.get_object()):
            if obj.Proxy is self or getattr(obj.Proxy,'object_group',None) == 'baseplate':
                continue
            if not hasattr(obj.Proxy,'contract'):
                continue
            contract = obj.Proxy.contract()
            if contract.catalog_id == 'displacement-pbs-holder':
                fused.append(obj)
            elif attachments.integration_profile(obj.Proxy):
                integrated.append(obj)
            elif attachments.profile(obj.Proxy):
                hardware.append(obj)
            elif contract.catalog_id in ('rotation','translation'):
                if not any(attachments.profile(child.Proxy) for child in descendants(obj)):
                    raise ValueError('No verified baseplate attachment profile yet for '+contract.catalog_id)
        if not hardware and not fused and not integrated:
            raise ValueError('No supported catalog mounts or integral supports in layout')
        shapes = []
        for obj in descendants(self.layout.get_object()):
            if getattr(obj.Proxy,'object_group',None) in ('beam_path','baseplate'):
                continue
            if hasattr(obj,'Shape') and not obj.Shape.isNull():
                shape = obj.Shape.copy()
                shape.Placement = self._relative(obj)
                shapes.append(shape)
        # Tight bounds avoid false recesses from inflated spline bounding boxes.
        bounds = Part.makeCompound(shapes).optimalBoundingBox()
        # Round outward to a convenient 5 mm stock grid, retaining the margin.
        x0 = math.floor((bounds.XMin-self.margin)/5)*5
        y0 = math.floor((bounds.YMin-self.margin)/5)*5
        width = math.ceil((bounds.XMax+self.margin)/5)*5-x0
        depth = math.ceil((bounds.YMax+self.margin)/5)*5-y0
        plate = Part.makeBox(width,depth,self.thickness,App.Vector(x0,y0,-self.thickness))
        operations, pockets, heights, native_heights = [], [], {}, {}
        for obj in hardware:
            contract = obj.Proxy.contract()
            profile = attachments.profile(obj.Proxy)
            frames = {f.name:f for f in contract.frames}
            placement = self._relative(obj)
            seat = placement.multVec(App.Vector(*frames[profile['seat_frame']].position))
            optical = placement.multVec(App.Vector(*frames['optical'].position))
            heights[obj.Name] = optical.z
            native_heights[obj.Name] = frames['optical'].position[2] - frames[profile['seat_frame']].position[2]
            local_up = placement.Rotation.multVec(App.Vector(0,0,1))
            if (local_up-App.Vector(0,0,1)).Length > 1e-7:
                raise ValueError('Mount must stand upright for top-down plate machining: '+obj.Label)
            if seat.z > .01:
                raise ValueError('Mount would float above plate; spacers are not allowed: '+obj.Label)
            if seat.z < -1e-6:
                shape = obj.Shape.copy();shape.Placement = placement
                b = shape.optimalBoundingBox()
                if seat.z-self.pocket_clearance <= -self.thickness+10:
                    raise ValueError('Insufficient stock beneath recessed mount for tapped hole')
                # A conservative rectangular machining pocket, with a flat seat.
                pocket = Part.makeBox(b.XLength+2*self.pocket_clearance,
                    b.YLength+2*self.pocket_clearance,-seat.z+.01,
                    App.Vector(b.XMin-self.pocket_clearance,b.YMin-self.pocket_clearance,seat.z))
                plate = plate.cut(pocket)
                pockets.append(dict(mount=obj.Label,depth_mm=-seat.z,clearance_mm=self.pocket_clearance))
            for record, pocket in attachments.clearance_pockets(obj.Proxy, placement):
                bottom = pocket.optimalBoundingBox().ZMin
                if bottom < -self.thickness + .5:
                    raise ValueError('Clearance pocket leaves insufficient stock')
                plate = plate.cut(pocket)
                pockets.append(dict(mount=obj.Label, kind='hardware_clearance',
                    depth_mm=-bottom, **record))
            for operation in attachments.operations(obj.Proxy, placement):
                center = App.Vector(*operation['center_mm'])
                if center.z-operation['depth_mm']-attachments.tip_height(operation['diameter_mm']) < -self.thickness+.5:
                    raise ValueError('Blind hole breaks through or leaves insufficient stock')
                plate = plate.cut(attachments.bore(operation))
                operation.update(mount=obj.Label, mount_object=obj.Name, assembly=obj.Parent.Label)
                operations.append(operation)
        # The PBS holder is part of the stock, including its existing clamp bore.
        self.integrated_names = []
        for obj in fused:
            shape = obj.Shape.copy();shape.Placement = self._relative(obj)
            heights[obj.Name] = self._relative(obj).multVec(App.Vector(0, 0, 0)).z
            plate = plate.fuse(shape)
            # Fusion with the stock must not refill the existing clamp bore.
            frames = {f.name:f for f in obj.Proxy.contract().frames}
            for hole in obj.Proxy.contract().holes:
                center = self._relative(obj).multVec(App.Vector(*frames[hole.frame].position))
                radius = hole.diameter_mm/2
                tip_height = radius/math.tan(math.radians(59))
                bore = Part.makeCylinder(radius,hole.depth_mm+.01,
                    center+App.Vector(0,0,.01),App.Vector(0,0,-1))
                tip = Part.makeCone(radius,0,tip_height,
                    center-App.Vector(0,0,hole.depth_mm),App.Vector(0,0,-1))
                plate = plate.cut(bore.fuse(tip))
                operations.append(dict(kind='existing_clamp_bore',mount=obj.Label,
                    center_mm=list(center),axis=[0,0,-1],diameter_mm=hole.diameter_mm,
                    depth_mm=hole.depth_mm,thread=hole.thread,source=hole.source))
            self.integrated_names.append(obj.Name)
            if obj.ViewObject:
                obj.ViewObject.Visibility = False
        plate, integral_operations, integral_objects = attachments.fuse_integrated(
            plate, self.layout.get_object(), getattr(self, '_object', self.layout.get_object()))
        operations.extend(integral_operations)
        if integral_objects:
            # Stock union must not refill a neighboring mount's earlier bores.
            for operation in operations:
                operation = dict(operation)
                operation.setdefault('axis', [0,0,-1])
                plate = plate.cut(attachments.bore(operation))
        self.integrated_names.extend(obj.Name for obj in integral_objects)
        for obj in integral_objects:
            frames = {f.name:f for f in obj.Proxy.contract().frames}
            seat = frames[attachments.integration_profile(obj.Proxy)['seat_frame']]
            heights[obj.Name] = self._relative(obj).multVec(App.Vector(*frames['optical'].position)).z
            native_heights[obj.Name] = frames['optical'].position[2] - seat.position[2]
        plate = plate.removeSplitter()
        if not plate.isValid() or len(plate.Solids) != 1:
            raise ValueError('Machined plate and integrated holders must form one valid solid')
        self.plan = dict(units='mm',top_z=0,thickness_mm=self.thickness,
            plate_position_mm=list(getattr(self, '_object', self.layout.get_object()).Placement.Base),
            optical_height_mm=(next(iter(heights.values())) if len({round(v, 6) for v in heights.values()}) == 1 else None),
            optical_heights_mm=heights,native_optical_heights_mm=native_heights,stock_bounds=[x0,y0,width,depth],
            holes=operations,pockets=pockets,integrated_holders=self.integrated_names,
            note='Nominal machining model. Tap-drill cylinders carry thread annotations; threads are not helically modeled. No table attachment pattern has been added.')
        if integral_objects:
            bounds = plate.optimalBoundingBox()
            self.plan['stock_z_bounds_mm'] = [bounds.ZMin, bounds.ZMax]
            self.plan['stock_envelope_mm'] = [bounds.XLength, bounds.YLength, bounds.ZLength]
            self.plan['note'] += (' thickness_mm is the slab below Z=0; integral features rise above it. '
                                  'stock_envelope_mm gives the minimum bounding billet dimensions.')
        if hasattr(self, '_object'):
            self._object.MachiningPlan = json.dumps(self.plan,indent=2)
        return plate


def add(layout, label='Machined baseplate', position=(0,0,0), **parameters):
    """Add after mounting components are placed and recomputed; recompute normally."""
    definition = MachinedBaseplate(layout, **parameters)
    component = layout.add(Component(label, definition, recompute_priority=-2),position,0)
    component.make_property('MachiningPlan','App::PropertyString',visible=True)
    definition._object = component.get_object()
    return component, definition
