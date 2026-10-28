"""CAD-only adapters for curated lab assemblies used by the schematic registry.

Imported lazily by PartSpec.instantiate or an exported script, never by the
portable model, compiler, or numerical worker.
"""

from PyOpticL import lab_catalog
from PyOpticL.beam_path import Stop, TransmissionGrating
from PyOpticL.roof_mirror import RoofGeometry, MountedRoof, RoofOptic
from PyOpticL.ray_math import grating_surface_angle


def vendor(part):
    return lab_catalog.VendorPart(part)


def mirror(mount, diameter, thickness):
    return lab_catalog.definition("mirror", mount=mount, thickness=thickness)


def d_mirror(optic, diameter, thickness, edge_distance=1, mount=None):
    from .registry import d_mirror_geometry

    geometry = d_mirror_geometry(optic)
    if diameter != 2 * geometry["radius_mm"] or thickness != geometry["thickness_mm"]:
        raise ValueError("Purchased D mirrors have fixed diameter and thickness")
    if mount is None:
        return lab_catalog.definition(optic, edge_distance=edge_distance)
    return lab_catalog.definition("d_mirror", mount=mount, optic=optic, edge_distance=edge_distance)


def waveplate(mount, diameter, thickness, fast_axis_angle, retardance):
    return lab_catalog.definition(
        "rotation", mount=mount, thickness=thickness, retardance=retardance, fast_axis_angle=fast_axis_angle
    )


def coupling(mount, receiving=False):
    result = lab_catalog.definition("coupling", mount=mount)
    if receiving:
        result.interfaces = lambda: [Stop(position=(0, 0, 0), rotation=(0, 0, 0), diameter=5)]
    return result


def pbs(rotate_cube=False, side_length=12.7, ref_polarization=0):
    result = lab_catalog.definition("pbs")
    result.children[0][1].rotate_cube = rotate_cube
    result.children[0][1].ref_polarization = ref_polarization
    # This preset retains the catalog's ideal polarization-selective coating.
    return result


def iris(aperture_diameter=0.5):
    return lab_catalog.definition("iris", aperture_diameter=aperture_diameter)


def slit(slit_width=1):
    return lab_catalog.definition("slit", slit_width=slit_width)


def crystal(mounted=True):
    return lab_catalog.definition("crystal_holder" if mounted else "crystal_holder_bare")


def roof(orientation="horizontal", beam_separation=12.7, mounted=True, reverse=False):
    geometry = RoofGeometry(orientation, beam_separation)
    if reverse:
        # Reframe at the resolved incident port. The same finite facets are
        # entered in opposite order; all supports follow the reframed origin.
        geometry.center *= -1
        geometry.output = 2 * geometry.center
    return MountedRoof(geometry) if mounted else RoofOptic(geometry)


def grating(incidence_angle=49.9, order=1, design_wavelength=1550, mounted=True, mirrored=False):
    from PyOpticL.grating import MountedGrating, GratingOptic

    if mounted:
        return MountedGrating(
            design_wavelength=design_wavelength, incidence_angle=incidence_angle, order=order,
            mirrored=mirrored,
        )
    result = GratingOptic(order=order)
    angle = grating_surface_angle(incidence_angle, mirrored)
    result.shape = lambda: lab_catalog.transform(GratingOptic.shape(result), rotation=(0, 0, angle))
    result.interfaces = lambda: [TransmissionGrating(rotation=(0, 0, angle), order=order)]
    return result
