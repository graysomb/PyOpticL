"""Editable CPA starter routes; dimensions and optical prescription are provisional.

The upper stretcher mirror returns the beam to the launching fiber collimator
through the shared VA100, gratings and telescope lenses. The compressor uses two
physical gratings twice and a horizontal roof return, feeding SHG directly.
The EDFA is external. The separate 775 nm source
marks the crystal exit and does not calculate nonlinear conversion.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from PyOpticL.schematic import (
    Schematic,
    Connection,
    Endpoint,
    compile_schematic,
    save_schematic,
)
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import intersect, trace_scene
from PyOpticL.ray_math import add, mul, yaw
from PyOpticL.schematic.optic_geometry import dichroic_transmission

LENS_FOCAL_LENGTH_MM = 30.0
STRETCHER_FOCAL_LENGTH_MM = 500.0
STRETCHER_GRATING_GAP_MM = 70.0
STRETCHER_LENS_SEPARATION_MM = 1000.0
STRETCHER_COUPLER_TO_MIRROR_MM = 180.0
STRETCHER_MIRROR_TO_GRATING_MM = 150.0
COMPRESSOR_GRATING_SEPARATION_MM = (
    STRETCHER_LENS_SEPARATION_MM - 2 * STRETCHER_GRATING_GAP_MM
)
RETURN_SEPARATION_MM = 9.0
REAR_DICHROIC_TO_MIRROR_MM = 110.0
REAR_MIRROR_TO_COUPLER_MM = 120.0
H = 12.7
T = 101.62794830005953


def new(title):
    d = Schematic(title)
    d.layout = {"poses": {}, "projection": "XY", "splitters": {}}
    d.settings.update(plate_thickness=30.0, open_length=80.0)
    return d


def node(d, ref, kind, preset, pos, angle=0, **params):
    n = d.add_node(kind)
    n.id = ref
    n.reference = ref
    select_preset(n, preset)
    n.parameters.update(params)
    d.layout["poses"][ref] = [*pos, H, angle]
    return n


def edge(d, a, b, aport="B", bport="A", apass="", bpass="", length=None):
    d.connections.append(
        Connection(
            "e" + str(len(d.connections)),
            Endpoint(a.id, aport, apass),
            Endpoint(b.id, bport, bpass),
            length=length,
        )
    )


def chain(d, nodes):
    for a, b in zip(nodes, nodes[1:]):
        edge(
            d,
            a,
            b,
            "beam" if a.kind in ("source", "fiber_source") else "B",
            "beam" if b.kind in ("output", "fiber_output") else "A",
        )


def stretcher():
    d = new("CPA draft — stretcher")
    m = node(d, "ST_M1", "mirror", "POLARIS-K1VS2", (760, 550), 270)
    i = node(d, "ST_Iris", "slit", "VA100", (760, 475), -90, slit_width=1.0)
    g = node(d, "ST_G1", "grating", "MK05S", (760, 400), -90)
    v = yaw((1, 0, 0), T - 90)

    def p(dist):
        q = add((760, 400, 0), mul(v, dist))
        return q[:2]

    l1 = node(
        d,
        "ST_L1",
        "lens",
        "POLARIS-L1G",
        p(STRETCHER_GRATING_GAP_MM),
        T - 90,
        focal_length=STRETCHER_FOCAL_LENGTH_MM,
    )
    l2 = node(
        d,
        "ST_L2",
        "lens",
        "POLARIS-L1G",
        p(STRETCHER_GRATING_GAP_MM + STRETCHER_LENS_SEPARATION_MM),
        T - 90 + 180,
        focal_length=STRETCHER_FOCAL_LENGTH_MM,
    )
    q = p(2 * STRETCHER_GRATING_GAP_MM + STRETCHER_LENS_SEPARATION_MM)
    g2 = node(d, "ST_G2", "grating", "MK05S", q, T - 90, mirrored=1)
    steering = node(
        d, "ST_M2", "mirror", "POLARIS-K05VS2",
        (q[0], q[1] - STRETCHER_MIRROR_TO_GRATING_MM), 135,
    )
    hwp = node(
        d, "ST_HWP1", "hwp", "FBR",
        (q[0], q[1] - STRETCHER_MIRROR_TO_GRATING_MM / 2), 90,
        fast_axis_angle=0,
    )
    coupler = node(
        d,
        "To_EDFA",
        "fiber_source",
        "POLARIS-K05T6",
        (q[0] - STRETCHER_COUPLER_TO_MIRROR_MM, q[1] - STRETCHER_MIRROR_TO_GRATING_MM),
        0,
        wavelength=1550,
        waist=0.2,
        power=0.001,
    )
    returning = {}
    for part in (i, g, l1, l2, g2, hwp, steering, coupler):
        visit = d.add_pass(part.id)
        visit.id = part.id + "_return"
        visit.centered = True
        returning[part.id] = visit.id
    # Launch into the former receiving port and traverse the same optics twice.
    chain(d, [coupler, steering, hwp])
    edge(d, hwp, g2, "B", "B")
    for first, second in zip((g2, l2, l1, g), (l2, l1, g, i)):
        edge(d, first, second, "A", "B")
    edge(d, i, m, "A", "A")
    edge(d, m, i, "B", "A", bpass=returning[i.id])
    for first, second in zip((i, g, l1, l2), (g, l1, l2, g2)):
        edge(d, first, second, "B", "A", returning[first.id], returning[second.id])
    edge(d, g2, hwp, "B", "B", returning[g2.id], returning[hwp.id])
    edge(d, hwp, steering, "A", "A", returning[hwp.id], returning[steering.id])
    edge(d, steering, coupler, "B", "beam", returning[steering.id], returning[coupler.id])
    return d


def compressor():
    d = new("CPA draft — compressor and crystal")
    s = node(
        d,
        "From_EDFA",
        "fiber_source",
        "POLARIS-K05T6",
        (500, -150),
        180,
        wavelength=1550,
        waist=0.2,
        power=0.5,
    )
    hwp = node(d, "CP_HWP1", "hwp", "FBR", (420, -150), 180, fast_axis_angle=0)
    m = node(d, "CP_M1", "mirror", "POLARIS-K05VS2", (320, -150), 45)
    g1 = node(d, "CP_G1", "grating", "MK05S", (320, 0), 90)
    v = yaw((1, 0, 0), 90 + T)
    q = add((320, 0, 0), mul(v, COMPRESSOR_GRATING_SEPARATION_MM))
    g2 = node(d, "CP_G2", "grating", "MK05S", q[:2], 90 + T, mirrored=1)
    roof = node(
        d,
        "CP_Roof",
        "roof",
        "horizontal",
        (q[0], q[1] + 160),
        90,
        beam_separation=RETURN_SEPARATION_MM,
    )
    p2 = d.add_pass(g2.id)
    p2.id = "CP_G2_return"
    p2.centered = False
    p1 = d.add_pass(g1.id)
    p1.id = "CP_G1_return"
    p1.centered = False
    # Reciprocal return through both physical gratings, starting at roof exit.
    origin = (q[0] + RETURN_SEPARATION_MM, q[1] + 160, H)
    direction = (0, -1, 0)
    # Temporary connections are enough for plane intersection; topology is only used by roofs.
    hit2 = intersect(d, g2, d.layout["poses"][g2.id], origin, direction, None)[1]
    hit1 = intersect(
        d, g1, d.layout["poses"][g1.id], hit2, yaw((1, 0, 0), T - 90), None
    )[1]
    x = hit1[0]
    m2 = node(d, "CP_M2", "mirror", "POLARIS-K05VS2", (x, -220), 135)
    shg_hwp = node(d, "SHG_HWP1", "hwp", "FBR", (260, -220), 180, fast_axis_angle=0)
    fl = node(
        d,
        "SHG_L1",
        "lens",
        "POLARIS-L05G",
        (200, -220),
        180,
        focal_length=LENS_FOCAL_LENGTH_MM,
    )
    xt = node(d, "SHG_Crystal", "crystal", "bracketed", (100, -220), 180)
    out = node(d, "Crystal_1550_exit", "output", "open", (86.3, -220), 180)
    chain(d, [s, hwp, m, g1])
    edge(d, g1, g2, length=COMPRESSOR_GRATING_SEPARATION_MM)
    edge(d, g2, roof)
    edge(d, roof, g2, "B", "B", bpass=p2.id)
    edge(d, g2, g1, "A", "B", apass=p2.id, bpass=p1.id)
    edge(d, g1, m2, "A", "A", apass=p1.id)
    chain(d, [m2, shg_hwp, fl, xt, out])
    return d


def shg_output_parts(d):
    l = node(
        d,
        "SHG_L2",
        "lens",
        "POLARIS-L05G",
        (0, -220),
        0,
        focal_length=LENS_FOCAL_LENGTH_MM,
    )
    m = node(d, "SHG_M1", "dichroic", "MHV-12.7L-R", (-100, -220), -45)
    return l, m


def output775():
    d = new("CPA draft — 775 nm reflected output")
    s = node(d, "SHG_775_boundary", "source", "beam", (86.3, -220), 180,
             wavelength=775, waist=0.1, power=0.075)
    l, m = shg_output_parts(d)
    o = node(d, "Output_775", "output", "open", (-100, -330), -90)
    chain(d, [s, l, m, o])
    return d


def residual1550():
    d = new("CPA draft — residual 1550 nm transmitted output")
    s = node(d, "SHG_1550_boundary", "source", "beam", (86.3, -220), 180,
             wavelength=1550, waist=0.2, power=0.425)
    l, m = shg_output_parts(d)
    exit, direction, _ = dichroic_transmission(
        (-100, -220, H), (-1, 0, 0), yaw((1, 0, 0), -45), 3, 1.5
    )
    point = add(exit, mul(direction, REAR_DICHROIC_TO_MIRROR_MM))
    steering = node(d, "SHG_IR_M1", "mirror", "POLARIS-K05VS2", point[:2], -45)
    out = node(d, "Residual_1550", "fiber_output", "POLARIS-K05T6",
               (point[0], point[1] - REAR_MIRROR_TO_COUPLER_MM), 90)
    chain(d, [s, l, m, steering, out])
    return d


ASSUMPTIONS = [
    "The rear 1550 nm output uses a 12.7 mm mirror SHG_IR_M1 in a POLARIS-K05VS2 mount, then an existing F260FC-1550/AD1109F/POLARIS-K05T6 fiber coupler with its integral lens. Editable starter distances are 110 mm from the dichroic rear surface to the steering mirror and 120 mm from that mirror to the receiving coupler. No additional coupling lens or fiber cable is modeled; fiber mode matching is not validated.",
    "The final SHG optic is an ideal dichroic: 700–850 nm reflects (including 775 nm), while 1550 nm transmits through a nominal 3 mm, n=1.5 parallel plate. The optic's exact part/coating is not yet selected. The MHV-12.7L-R mount uses its existing 12.7 mm, 3 mm-thick optic seating contract; the rear beam clearance is checked against the pinned vendor CAD.",
    "Separate 775 nm and residual 1550 nm traces share one output lens and one dichroic assembly. The residual 1550 nm display power of 425 mW is only illustrative (500 minus 75 mW, ignoring losses), not a conversion or residual-power prediction. Both wavelengths and boundary beam parameters remain editable.",
    "Both stretcher lenses are 25.4 mm (1 inch) diameter in POLARIS-L1G mounts. The stretcher end retroreflecting mirror ST_M1 is 25.4 mm diameter in a POLARIS-K1VS2 mount. The final compressor mirror CP_M2 is 12.7 mm (1/2 inch) diameter in a POLARIS-K05VS2 mount. Their mounting pockets and drilling follow the catalog contracts.",
    "Stretcher lenses have editable 500 mm focal lengths, 1000 mm mutual spacing and 70 mm gaps to the adjacent gratings. ST_L1 and ST_L2 have opposite local +X facing directions; ST_L2 and its mount are rotated 180 degrees. Facing arrows are visual annotations, not a specified lens surface prescription. SHG lenses retain editable, provisional 30 mm focal lengths.",
    "SHG_L1 and SHG_L2 have opposing lens-mount directions. The output lens SHG_L2 and its POLARIS-L05G mount face local +X, opposite the input lens SHG_L1; their positions, diameters and focal lengths are retained.",
    "Three half-wave plates use catalog FBR rotation mounts: one between the stretcher steering mirror ST_M2 and first encountered grating ST_G2, one directly after the compressor fiber collimator, and one directly before SHG_L1. Their fast-axis angles are editable and provisionally 0 degrees; operating polarization settings remain to be determined.",
    "Stretcher launch order is coupler -> ST_M2 steering mirror -> ST_HWP1 -> ST_G2. The coupler is provisionally 180 mm from the steering mirror; the mirror is 150 mm from the grating with the waveplate halfway between. The mirror and waveplate are shared by the retroreflected return. These starter distances are editable.",
    "The upper stretcher mirror is normal to the arriving ray and retroreflects it. The existing fiber collimator is a shared launch/return boundary; external seed/return fiber routing is not modeled.",
    "Four LightSmyth/MK05S assemblies: two stretcher gratings and two compressor gratings. Both pairs are shared by forward and return passes; the stretcher also reuses the same VA100 and telescope lenses.",
    "Compressor grating centers are separated by 1000 - 2*70 = 860 mm along the outgoing inter-grating beam. This distance is an editable schematic length constraint; the roof and return route follow the second grating.",
    "The stretcher filter location uses the tunable VA100 slit with its catalog bracket and drill contract. Slit width is editable and provisionally 1 mm; spectral bandwidth remains unconfirmed.",
    "The compressor LO pickoff and its branch are omitted. The return from CP_G1 feeds CP_M2 directly, then the SHG half-wave plate and lens.",
    "EDFA remains external, bounded by two existing fiber collimators with integral lenses. A third integral-lens coupler receives the rear 1550 nm output; no additional coupling lenses, fibers or EDFA package are modeled.",
    "1550 nm and 775 nm are separate traces joined at the crystal exit. No gain, pulse dispersion, SHG efficiency or phase matching is predicted.",
    "500 mW amplifier input and 75 mW 775 nm display values follow the reference labels; seed power and all Gaussian input waists are illustrative.",
    "Rendered beams are constant-width center-ray guides, not validated Gaussian beam envelopes.",
    "The 30 mm plate and all machining are a review draft; do not fabricate before confirming distances, optics and clearances.",
]


def documents():
    return {
        "stretcher": stretcher(),
        "compressor": compressor(),
        "output-775": output775(),
        "residual-1550": residual1550(),
    }


def generate(folder=None):
    folder = Path(folder or Path(__file__).parent)
    folder.mkdir(parents=True, exist_ok=True)
    for name, d in documents().items():
        r = compile_schematic(d)
        if not r.ok:
            raise ValueError([item.message for item in r.diagnostics])
        save_schematic(d, folder / (name + ".pyopticl-schematic.json"))
        (folder / (name + ".py")).write_text(r.source)
    (folder / "assumptions.json").write_text(json.dumps(ASSUMPTIONS, indent=2) + "\n")
    return folder


if __name__ == "__main__":
    generate()
