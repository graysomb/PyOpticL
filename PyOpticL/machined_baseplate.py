"""CAD-datum-driven plate machining for the lab catalog.

Plate top is Z=0 in the supplied layout. No supports/spacers are introduced.
Tapped holes are represented by tap-drill bores and explicit thread metadata.
"""
import json
import math
import FreeCAD as App
import Part
from PyOpticL import lab_catalog
from PyOpticL.layout import Component

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
        return self.layout.get_object().Placement.inverse() * obj.Placement

    def shape(self):
        hardware, fused = [], []
        for obj in descendants(self.layout.get_object()):
            if obj.Proxy is self or getattr(obj.Proxy,'object_group',None) == 'baseplate':
                continue
            if not hasattr(obj.Proxy,'contract'):
                continue
            contract = obj.Proxy.contract()
            if contract.catalog_id == 'displacement-pbs-holder':
                fused.append(obj)
            elif contract.part_number in PROFILES:
                hardware.append(obj)
            elif contract.catalog_id == 'iris' and hasattr(obj.Proxy, 'baseplate_profile'):
                hardware.append(obj)
            elif contract.catalog_id in ('rotation','translation'):
                raise ValueError('No verified baseplate attachment profile yet for '+contract.catalog_id)
        if not hardware and not fused:
            raise ValueError('No supported catalog mounts or integral PBS supports in layout')
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
        operations, pockets = [], []
        for obj in hardware:
            contract = obj.Proxy.contract()
            part = contract.part_number or contract.catalog_id
            if contract.catalog_id == 'iris':
                profile = obj.Proxy.baseplate_profile()
            else:
                profile = PROFILES[part]
                if lab_catalog.asset_record(part)['sha256'] != profile['step_sha256']:
                    raise ValueError('Mounting profile must be reverified for revised CAD: '+part)
            frames = {f.name:f for f in contract.frames}
            placement = self._relative(obj)
            seat = placement.multVec(App.Vector(*frames[profile['seat_frame']].position))
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
            for name in profile['screws']+profile['dowels']:
                frame = frames[name]
                center = placement.multVec(App.Vector(*frame.position))
                if abs(center.z-seat.z) > .01:
                    raise ValueError('Attachment hole is not on selected mounting face')
                if name in profile['screws']:
                    diameter, drill_depth = 3.3, 10.
                    operation = dict(kind='tapped',thread='M4 x 0.7',thread_depth_mm=8.,
                        diameter_mm=diameter,depth_mm=drill_depth,
                        note='M4 selected explicitly from vendor #8/M4 clearance compatibility; 3.3 mm tap drill, 8 mm usable thread.')
                else:
                    diameter = profile['dowel']['plate_diameter_mm']
                    drill_depth = profile['dowel']['plate_depth_mm']
                    operation = dict(kind='dowel',diameter_mm=diameter,depth_mm=drill_depth,
                        diameter_limits_mm=profile['dowel']['plate_diameter_limits_mm'],
                        depth_tolerance_mm=profile['dowel']['plate_depth_tolerance_mm'],
                        pin=profile['dowel']['pin'],projection_mm=profile['dowel']['pin_projection_mm'])
                radius = diameter/2
                tip_height = radius/math.tan(math.radians(59))
                if center.z-drill_depth-tip_height < -self.thickness+.5:
                    raise ValueError('Blind hole breaks through or leaves insufficient stock')
                bore = Part.makeCylinder(radius,drill_depth+.01,
                    App.Vector(center.x,center.y,center.z+.01),App.Vector(0,0,-1))
                tip = Part.makeCone(radius,0,tip_height,
                    App.Vector(center.x,center.y,center.z-drill_depth),App.Vector(0,0,-1))
                plate = plate.cut(bore.fuse(tip))
                operation.update(mount=obj.Label,mount_object=obj.Name,assembly=obj.Parent.Label,part=part,interface=name,
                    center_mm=list(center),axis=[0,0,-1],source=profile['source'],
                    step_sha256=profile['step_sha256'],drawing_sha256=profile['drawing_sha256'])
                operations.append(operation)
        # The PBS holder is part of the stock, including its existing clamp bore.
        self.integrated_names = []
        for obj in fused:
            shape = obj.Shape.copy();shape.Placement = self._relative(obj)
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
        plate = plate.removeSplitter()
        if not plate.isValid() or len(plate.Solids) != 1:
            raise ValueError('Machined plate and integrated holders must form one valid solid')
        self.plan = dict(units='mm',top_z=0,thickness_mm=self.thickness,
            optical_height_mm=optical_height(),stock_bounds=[x0,y0,width,depth],
            holes=operations,pockets=pockets,integrated_holders=self.integrated_names,
            note='Nominal machining model. Tap-drill cylinders carry thread annotations; threads are not helically modeled. No table attachment pattern has been added.')
        if hasattr(self, '_object'):
            self._object.MachiningPlan = json.dumps(self.plan,indent=2)
        return plate


def add(layout, label='Machined baseplate', **parameters):
    """Add after mounting components are placed and recomputed; recompute normally."""
    definition = MachinedBaseplate(layout, **parameters)
    component = layout.add(Component(label, definition, recompute_priority=-2),(0,0,0),0)
    component.make_property('MachiningPlan','App::PropertyString',visible=True)
    definition._object = component.get_object()
    return component, definition
