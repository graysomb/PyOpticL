"""LightSmyth T-1000C, direct MK05S seating, and a native baseplate adapter.

All geometry below is in the grating frame: +X into the substrate, +Y toward
the MK05S open side, and +Z along the grooves. MountedGrating rotates the
whole assembly so its nominal incident ray follows +X in the wrapper frame.
"""
import json
import FreeCAD as App
import Part

from PyOpticL import attachments
from PyOpticL.beam_path import TransmissionGrating, grating_angles
from PyOpticL.ray_math import grating_surface_angle
from PyOpticL.component_contract import ComponentContract, Frame, Hole, MechanicalInterface, Provenance, Thread
from PyOpticL.lab_catalog import DATA, Assembly, NominalScrew, _blind_bore, asset_record, transform, vendor_shape, _dofs

PART = 'LightSmyth-1336552'
MOUNT_URL = 'https://www.thorlabs.com/item/MK05S'


def reference():
    return json.loads((DATA/'grating_reference.json').read_text())


def _box(size, corner):
    return Part.makeBox(*size, App.Vector(*corner))


def optic_provenance():
    g = reference()['grating']
    return (Provenance(g['product_url'],'documented',note=g['geometry_status']),
            Provenance(g['datasheet_url'],'documented',g.get('datasheet_sha256'),
                '1000 grooves/mm; grooves parallel to 12.3 mm edge; 49.9 deg nominal AOI. '
                'Ideal single-order thin interface: no calibrated efficiency, substrate displacement/OPL, '
                'coating phase, or Gaussian anamorphism.'))


def mechanical_provenance():
    r = reference()
    return (Provenance(MOUNT_URL,'cad_verified',r['step_sha256'],
        r['drawing']+'; all 25 purchased solids unchanged. Native reference pose; '
        'Grating seats directly in the pocket, centered under the existing nylon lock. '
        'The reference lock needs 0.55875 mm nominal advance. Direct mounting is user specified; '
        'CAD seating is verified, while physical retention and clamp force remain unvalidated.'),)


class MK05SMount:
    object_group = 'mounts'
    object_color = (.23,.25,.28)
    apply_drilling = False
    preserve_topology = True
    part_numbers = ['MK05S']

    def shape(self):
        r = reference()
        if asset_record('MK05S')['sha256'] != r['step_sha256']:
            raise ValueError('MK05S CAD revision requires new datum verification')
        return transform(vendor_shape('MK05S'),**r['normalization'])

    def contract(self):
        r = reference()
        rotation = App.Rotation('XYZ',*r['normalization']['rotation'])
        origin = App.Vector(*r['normalization']['origin'])
        frames = [Frame('origin'),Frame('optical'),
                  Frame('mounting_face',tuple(r['adapter_center_top_mm']))]
        holes, interfaces = [], []
        for h in r['source_mounting_holes']:
            point = rotation.multVec(App.Vector(*h['center_mm'])-origin)
            # Hole axis points inward from the mounting face.
            axis = -rotation.multVec(App.Vector(*h['axis']))
            angles = App.Rotation(App.Vector(0,0,1),axis).toEulerAngles('XYZ')
            frames.append(Frame(h['name'],tuple(point),tuple(angles)))
            holes.append(Hole(h['name'],h['name'],h['diameter_mm'],h['trimmed_max_depth_mm'],
                h['thread'],source=r['drawing']+'; STEP uses nominal thread-major cylinders; '
                'curved exit, conservative cylindrical extent 3.5865 mm, maximum 3.80948 mm'))
            interfaces.append(MechanicalInterface(h['name'],h['name'],'thread',
                Thread('4-40 UNC','internal',2.8448,.635),
                seating='Selected flat mounting face; two alternative faces at 90 degrees.',
                engagement_mm=r['adapter']['post_straight_engagement_mm'] if h['name']=='bottom_post' else None))
        return ComponentContract('MK05S','1','Thorlabs','MK05S','purchased',frames=tuple(frames),
            holes=tuple(holes),interfaces=tuple(interfaces),
            dofs=_dofs(('tip','tilt'),'directly mounted grating',MOUNT_URL),
            provenance=mechanical_provenance())


class GratingOptic:
    object_group = 'optics'
    object_color = (.64,.76,.85)
    apply_drilling = False
    part_numbers = ['1336552']

    def __init__(self, order=1, optical=True):
        TransmissionGrating(order=order)  # Shared validation, including integer order.
        self.order, self.optical = order, optical

    def shape(self):
        return _box((.95,31.8,12.3),(0,-15.9,-6.15))

    def interfaces(self):
        return [TransmissionGrating(order=self.order)] if self.optical else []

    def contract(self):
        return ComponentContract(PART,'1','Coherent LightSmyth','1336552','purchased',
            frames=(Frame('origin'),Frame('optical'),Frame('groove_axis')),
            optical_reference='optical',provenance=optic_provenance())


class GratingAdapter:
    object_group = 'adapters'
    object_color = (.48,.6,.52)
    apply_drilling = False
    drill_groups = ('baseplate',)
    part_numbers = []

    def __init__(self):
        self.top = App.Vector(*reference()['adapter_center_top_mm'])
        self.floor = self.top-App.Vector(0,0,10)

    def shape(self):
        body = _box((40,50,10),tuple(self.floor-App.Vector(20,25,0)))
        for x,y in reference()['adapter']['screw_xy_mm']:
            p = self.top+App.Vector(x,y,.01)
            body = body.cut(Part.makeCylinder(2.25,10.02,p,App.Vector(0,0,-1)))
            body = body.cut(Part.makeCylinder(3.75,4.41,p,App.Vector(0,0,-1)))
        for x,y in reference()['adapter']['pin_xy_mm']:
            body = body.cut(_blind_bore(tuple(self.floor+App.Vector(x,y,0)),2.05,2.,(0,0,1)))
        body = body.cut(Part.makeCylinder(1.55,10.02,self.floor-App.Vector(0,0,.01)))
        body = body.cut(Part.makeCylinder(2.75,3.51,self.floor-App.Vector(0,0,.01)))
        return body.removeSplitter()

    def contract(self):
        frames = [Frame('optical'),Frame('mounting_face',tuple(self.floor)),
                  Frame('mount_top',tuple(self.top)),Frame('mount_screw',tuple(self.floor),(0,0,0))]
        holes = [Hole('mount_screw','mount_screw',3.1,10.,counterbore_mm=5.5,
            source='4-40 clearance; underside counterbore 3.5 mm deep')]
        for kind,positions in (('plate',reference()['adapter']['screw_xy_mm']),
                               ('pin',reference()['adapter']['pin_xy_mm'])):
            for i,(x,y) in enumerate(positions,1):
                name = kind+'_'+str(i)
                frames.append(Frame(name,tuple(self.floor+App.Vector(x,y,0))))
                holes.append(Hole(name,name,4.5 if kind=='plate' else 2.05,
                    10. if kind=='plate' else 2.,counterbore_mm=7.5 if kind=='plate' else None,
                    source='M4 clearance, top counterbore 4.4 mm' if kind=='plate' else 'Blind locating bore into adapter, 118 degree tip'))
        return ComponentContract('grating-adapter','1','Lab','GRATING-ADAPTER','fabricated',
            frames=tuple(frames),holes=tuple(holes),optical_reference='optical',provenance=mechanical_provenance())

    def baseplate_profile(self):
        dowel = json.loads((DATA/'alignment_iris_reference.json').read_text())['mounting_profile']['dowel']
        return dict(seat_frame='mounting_face',screws=['plate_1','plate_2'],dowels=['pin_1','pin_2'],
            dowel=dowel,optical_height_mm=reference()['assembly_height_mm'],
            source='Custom grating adapter; MK05S drawing TTN193112-E0W A',
            step_sha256=reference()['step_sha256'],drawing_sha256=reference()['drawing_sha256'])

    def drill(self):
        return attachments.footprint(self)


class MountedGrating(Assembly):
    def __init__(self, mount='MK05S', design_wavelength=1550., incidence_angle=49.9, order=1, mirrored=False):
        if mount != 'MK05S':
            raise ValueError('Unsupported grating mount: '+str(mount))
        self.angles = grating_angles(design_wavelength,incidence_angle,order)
        self.mirrored = bool(mirrored)
        if self.mirrored:
            self.angles['deflection_angle_deg'] *= -1
        self.incidence_angle, self.order = incidence_angle, order
        self.optical_rotation = (0,0,grating_surface_angle(incidence_angle, self.mirrored))
        rotation = App.Rotation('XYZ',*self.optical_rotation)
        adapter = GratingAdapter()
        children = [('LightSmyth grating',GratingOptic(order,optical=False),(0,0,0),(0,0,0)),
                    ('MK05S',MK05SMount(),(0,0,0),(0,0,0)),
                    ('Baseplate adapter',adapter,(0,0,0),(0,0,0))]
        children.append(('4-40 mount screw',NominalScrew('4-40 UNC x 3/8 in',2.8448,.635,9.525,4.62,2.84),
                         tuple(adapter.floor+App.Vector(0,0,3.5)),(180,0,0)))
        for x,y in reference()['adapter']['screw_xy_mm']:
            children.append(('M4 plate screw',NominalScrew('M4 x 0.7 x 12 mm',4,.7,12,7,4),
                             tuple(adapter.top+App.Vector(x,y,-4.4)),(0,0,0)))
        frames = [Frame('origin'),Frame('optical'),Frame('input'),
                  Frame('output',(0,0,0),(0,0,self.angles['deflection_angle_deg'])),
                  Frame('grating_surface',(0,0,0),self.optical_rotation),
                  Frame('native_mounting_face',tuple(rotation.multVec(adapter.top))),
                  Frame('mounting_face',tuple(rotation.multVec(adapter.floor)))]
        contract = ComponentContract('grating','1','Lab','','assembly',frames=tuple(frames),
            optical_reference='input',provenance=optic_provenance()+mechanical_provenance())
        transformed = [(label,definition,tuple(rotation.multVec(App.Vector(*point))),
            tuple((rotation*App.Rotation('XYZ',*angles)).toEulerAngles('XYZ')))
            for label,definition,point,angles in children]
        super().__init__(contract,transformed)

    def interfaces(self):
        return [TransmissionGrating(rotation=self.optical_rotation,order=self.order)]
