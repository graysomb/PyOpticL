"""Separate folded CPA variant; run to regenerate its editable routes and scripts.

Both dispersive stages are folded. The baseline supplies the SHG hardware;
its X/Y positions are retained at the compressor's lower output height.
No baseline schematic or artifact is overwritten by this generator.
"""
import importlib.util
import json
from pathlib import Path
import sys
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from PyOpticL.ray_math import add, mul, yaw, heading, grating_direction
from PyOpticL.schematic import Connection, Endpoint, compile_schematic, save_schematic
from PyOpticL.schematic.model import OpticalPass
from PyOpticL.schematic.optic_geometry import element_spec, roof_trace
from PyOpticL.schematic.scene_layout import intersect

spec = importlib.util.spec_from_file_location(
    "cpa_baseline", ROOT / "Designs/schematics/cpa/generate.py"
)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)

LENS_AXIS_HEIGHT_MM = 12.7
VERTICAL_BEAM_SEPARATION_MM = 5.65
BEAM_OFFSET_MM = VERTICAL_BEAM_SEPARATION_MM / 2
FOCAL_LENGTH_MM = 500.0
GRATING_GAP_MM = 70.0
GRATING_TO_PICKOFF_MM = 75.0
PICKOFF_TO_VA100_MM = 75.0
VA100_TO_RETRO_MM = 75.0
GRATING_TO_WAVEPLATE_MM = 150.0
GRATING_TO_STEERING_MM = 225.0
COUPLER_TO_STEERING_MM = 180.0
PLATE_TOP_Z_MM = 3.0
PLATE_THICKNESS_MM = 33.0
COMPRESSOR_AXIS_HEIGHT_MM = 12.7
COMPRESSOR_OFFSET_MM = BEAM_OFFSET_MM
# 15.4 mm spot spacing along the grating face at the current diffraction angle.
COMPRESSOR_HORIZONTAL_SEPARATION_MM = 9.538700742686107
COMPRESSOR_FOLD_DISTANCE_MM = baseline.COMPRESSOR_GRATING_SEPARATION_MM / 2
ROOF_INTERNAL_AXIAL_DEPTH_MM = 12.7
COMPRESSOR_INPUT_Y_MM = -300.0
COMPRESSOR_VERTICAL_ROOF_Y_MM = -100.0
COMPRESSOR_VERTICAL_ROOF_TANGENT_OFFSET_MM = -5.0
COMPRESSOR_PICKOFF_Y_MM = -220.0


def stretcher():
    d = baseline.new("CPA folded draft — off-axis stretcher")
    d.settings["plate_thickness"] = PLATE_THICKNESS_MM
    old = baseline.stretcher().layout["poses"]
    gx, gy = old["ST_G2"][:2]
    lx, ly = add((gx, gy, 0), mul(yaw((1, 0, 0), baseline.T - 90), -GRATING_GAP_MM))[:2]
    upper, lower = (
        LENS_AXIS_HEIGHT_MM + BEAM_OFFSET_MM,
        LENS_AXIS_HEIGHT_MM - BEAM_OFFSET_MM,
    )

    def put(ref, kind, preset, xy, z, angle, **parameters):
        n = baseline.node(d, ref, kind, preset, xy, angle, **parameters)
        d.layout["poses"][ref][2] = z
        return n

    put(
        "To_EDFA",
        "fiber_source",
        "POLARIS-K05T6",
        (gx - COUPLER_TO_STEERING_MM, gy - GRATING_TO_STEERING_MM),
        upper,
        0,
        wavelength=1550,
        waist=0.2,
        power=0.001,
    )
    put(
        "ST_M2",
        "mirror",
        "POLARIS-K05VS2",
        (gx, gy - GRATING_TO_STEERING_MM),
        upper,
        135,
    )
    put(
        "ST_HWP1",
        "hwp",
        "FBR",
        (gx, gy - GRATING_TO_WAVEPLATE_MM),
        upper,
        90,
        fast_axis_angle=0,
    )
    put(
        "ST_G2",
        "grating",
        "MK05S",
        (gx, gy),
        LENS_AXIS_HEIGHT_MM,
        baseline.T - 90,
        mirrored=1,
    )
    put(
        "ST_L2",
        "lens",
        "POLARIS-L1G",
        (lx, ly),
        LENS_AXIS_HEIGHT_MM,
        baseline.T - 90 + 180,
        focal_length=FOCAL_LENGTH_MM,
    )
    fold = add(
        (lx, ly, LENS_AXIS_HEIGHT_MM),
        mul(yaw((1, 0, 0), baseline.T - 90), -FOCAL_LENGTH_MM),
    )
    put(
        "ST_Fold",
        "mirror",
        "POLARIS-K1VS2",
        fold[:2],
        LENS_AXIS_HEIGHT_MM,
        baseline.T - 90,
    )
    py = gy - GRATING_TO_PICKOFF_MM
    put("ST_Pickoff", "mirror", "KM05DR", (gx, py), lower, 45, edge_distance=1)
    put(
        "ST_Iris",
        "slit",
        "VA100",
        (gx + PICKOFF_TO_VA100_MM, py),
        lower,
        0,
        slit_width=1,
    )
    put(
        "ST_M1",
        "mirror",
        "POLARIS-K1VS2",
        (gx + PICKOFF_TO_VA100_MM + VA100_TO_RETRO_MM, py),
        lower,
        180,
    )

    # Each tuple gives the stable visit ID, physical component and entry port.
    route = [
        ("To_EDFA", "To_EDFA", "beam"),
        ("ST_M2", "ST_M2", "A"),
        ("ST_HWP1", "ST_HWP1", "A"),
        ("ST_G2", "ST_G2", "B"),
        ("ST_L2", "ST_L2", "B"),
        ("ST_Fold", "ST_Fold", "A"),
        ("ST_L2_lower", "ST_L2", "A"),
        ("ST_G2_lower", "ST_G2", "A"),
        ("ST_Pickoff", "ST_Pickoff", "A"),
        ("ST_Iris", "ST_Iris", "A"),
        ("ST_M1", "ST_M1", "A"),
        ("ST_Iris_return", "ST_Iris", "B"),
        ("ST_Pickoff_return", "ST_Pickoff", "B"),
        ("ST_G2_lower_return", "ST_G2", "B"),
        ("ST_L2_lower_return", "ST_L2", "B"),
        ("ST_Fold_return", "ST_Fold", "A"),
        ("ST_L2_return", "ST_L2", "A"),
        ("ST_G2_return", "ST_G2", "A"),
        ("ST_HWP1_return", "ST_HWP1", "B"),
        ("ST_M2_return", "ST_M2", "B"),
        ("To_EDFA_return", "To_EDFA", "beam"),
    ]
    for visit, component, _ in route:
        if visit != component or component in ("ST_G2", "ST_L2"):
            d.passes.append(
                OpticalPass(
                    visit,
                    component,
                    "receive" if visit == "To_EDFA_return" else "pass",
                    centered=component not in ("ST_G2", "ST_L2"),
                )
            )
    for i, ((av, ac, entry), (bv, bc, incoming)) in enumerate(zip(route, route[1:])):
        outgoing = "beam" if ac == "To_EDFA" else "A" if entry == "B" else "B"
        d.connections.append(
            Connection(
                f"e{i}",
                Endpoint(ac, outgoing, "" if av == ac else av),
                Endpoint(bc, incoming, "" if bv == bc else bv),
            )
        )
    return d


def compressor():
    old = baseline.compressor()
    original_grating = old.node("CP_G1")
    old_pose = old.layout["poses"][original_grating.id]
    gx, gy = old_pose[:2]
    upper = COMPRESSOR_AXIS_HEIGHT_MM + COMPRESSOR_OFFSET_MM
    lower = COMPRESSOR_AXIS_HEIGHT_MM - COMPRESSOR_OFFSET_MM
    spec = element_spec(original_grating)
    face_angle = old_pose[3] + spec.normal_angle
    outgoing = grating_direction(
        (0, 1, 0), yaw((1, 0, 0), face_angle), yaw((0, 1, 0), face_angle), 1550, 1
    )
    roof_angle = heading(outgoing)
    roof_front = add(
        (gx, gy, COMPRESSOR_AXIS_HEIGHT_MM),
        mul(outgoing, COMPRESSOR_FOLD_DISTANCE_MM - ROOF_INTERNAL_AXIAL_DEPTH_MM),
    )
    # Compute the second spot from the finite roof, then center the grating
    # between the lateral spots. Moving its origin along its plane preserves
    # the first interaction point and leaves equal aperture margin at each side.
    points, back, _ = roof_trace(
        (0, 0, COMPRESSOR_OFFSET_MM),
        (1, 0, 0),
        COMPRESSOR_HORIZONTAL_SEPARATION_MM,
        reverse=True,
    )
    second = intersect(
        old,
        original_grating,
        old_pose,
        add(roof_front, yaw(points[-1], roof_angle)),
        yaw(back, roof_angle),
        None,
    )[1]
    d = baseline.new("CPA folded draft — four-pass compressor and crystal")
    d.settings["plate_thickness"] = PLATE_THICKNESS_MM

    def put(ref, kind, preset, xyz, angle, **parameters):
        n = baseline.node(d, ref, kind, preset, xyz[:2], angle, **parameters)
        d.layout["poses"][ref][2] = xyz[2]
        return n

    put(
        "From_EDFA",
        "fiber_source",
        "POLARIS-K05T6",
        (500, COMPRESSOR_INPUT_Y_MM, upper),
        180,
        wavelength=1550,
        waist=0.2,
        power=0.5,
    )
    put(
        "CP_HWP1",
        "hwp",
        "FBR",
        (420, COMPRESSOR_INPUT_Y_MM, upper),
        180,
        fast_axis_angle=0,
    )
    put(
        "CP_M1",
        "mirror",
        "POLARIS-K05VS2",
        (gx, COMPRESSOR_INPUT_Y_MM, upper),
        45,
    )
    put(
        "CP_G1",
        "grating",
        "MK05S",
        ((gx + second[0]) / 2, (gy + second[1]) / 2, COMPRESSOR_AXIS_HEIGHT_MM),
        old_pose[3],
    )
    put(
        "CP_HRoof",
        "roof",
        "horizontal",
        roof_front,
        roof_angle,
        beam_separation=COMPRESSOR_HORIZONTAL_SEPARATION_MM,
    )
    # Decenter the physical roof along its edge. The hit remains on the
    # displaced return ray, while the optic clears the two straight-through paths.
    vertical_roof_pose = add(
        (second[0], COMPRESSOR_VERTICAL_ROOF_Y_MM, upper),
        mul(yaw((0, 1, 0), -90), COMPRESSOR_VERTICAL_ROOF_TANGENT_OFFSET_MM),
    )
    put(
        "CP_VRoof",
        "roof",
        "vertical",
        vertical_roof_pose,
        -90,
        beam_separation=2 * COMPRESSOR_OFFSET_MM,
    )
    put(
        "CP_Pickoff",
        "mirror",
        "KM05DL",
        (gx, COMPRESSOR_PICKOFF_Y_MM, lower),
        135,
        edge_distance=1,
    )
    for n in old.nodes:
        if n.reference.startswith("SHG_") or n.reference == "Crystal_1550_exit":
            d.nodes.append(deepcopy(n))
            pose = list(old.layout["poses"][n.id])
            pose[2] += lower - baseline.H
            d.layout["poses"][n.id] = pose
    route = [
        ("From_EDFA", "From_EDFA", "beam"),
        ("CP_HWP1", "CP_HWP1", "A"),
        ("CP_M1", "CP_M1", "A"),
        ("CP_G1", "CP_G1", "A"),
        ("CP_HRoof", "CP_HRoof", "B"),
        ("CP_G1_2", "CP_G1", "B"),
        ("CP_VRoof", "CP_VRoof", "B"),
        ("CP_G1_3", "CP_G1", "A"),
        ("CP_HRoof_return", "CP_HRoof", "A"),
        ("CP_G1_4", "CP_G1", "B"),
        ("CP_Pickoff", "CP_Pickoff", "A"),
        ("SHG_HWP1", "SHG_HWP1", "A"),
        ("SHG_L1", "SHG_L1", "A"),
        ("SHG_Crystal", "SHG_Crystal", "A"),
        ("Crystal_1550_exit", "Crystal_1550_exit", "beam"),
    ]
    for visit, component, _ in route:
        if visit != component or component in ("CP_G1", "CP_HRoof", "CP_VRoof"):
            d.passes.append(OpticalPass(visit, component, centered=False))
    for i, ((av, ac, entry), (bv, bc, incoming)) in enumerate(zip(route, route[1:])):
        outgoing_port = "beam" if ac == "From_EDFA" else "A" if entry == "B" else "B"
        d.connections.append(
            Connection(
                f"e{i}",
                Endpoint(ac, outgoing_port, "" if av == ac else av),
                Endpoint(bc, incoming, "" if bv == bc else bv),
            )
        )
    return d


def lower_shg_output(document):
    """Rigidly lower the complete wavelength route, including virtual endpoints."""
    shift = COMPRESSOR_AXIS_HEIGHT_MM - COMPRESSOR_OFFSET_MM - baseline.H
    for pose in document.layout["poses"].values():
        pose[2] += shift
    return document


ASSUMPTIONS = [
    "Separate folded CPA variant with both dispersive stages folded. The baseline CPA files and artifacts are retained. Both folded stages use the same 5.65 mm upper/lower separation. The stretcher retains its X/Y positions, hardware and focal length; SHG and rear 1550 nm collection hardware retain their X/Y positions and optical parameters at the lower compressor output height.",
    f"The compressor uses one CP_G1 grating four times, one horizontal HRS1015-P01 roof twice, and one vertical HRS1015-P01 roof once. Its nominal axis is Z={COMPRESSOR_AXIS_HEIGHT_MM:g} mm, with input/output at Z={COMPRESSOR_AXIS_HEIGHT_MM + COMPRESSOR_OFFSET_MM:g}/{COMPRESSOR_AXIS_HEIGHT_MM - COMPRESSOR_OFFSET_MM:g} mm. The horizontal separation is {COMPRESSOR_HORIZONTAL_SEPARATION_MM:g} mm; the vertical roof shifts downward by {2*COMPRESSOR_OFFSET_MM:g} mm. All four grating passes are intentionally off axis, at the centers of the four quadrants of the 30.8 x 11.3 mm clear aperture: local face offsets (+/-7.7, +/-2.825) mm.",
    f"The horizontal roof's nominal virtual fold plane is {COMPRESSOR_FOLD_DISTANCE_MM:g} mm beyond the first grating hit. Its entrance plane is {COMPRESSOR_FOLD_DISTANCE_MM - ROOF_INTERNAL_AXIAL_DEPTH_MM:g} mm away, accounting for the measured roof's {ROOF_INTERNAL_AXIAL_DEPTH_MM:g} mm internal axial depth. Actual path lengths include the finite roof path and lateral walkoff; a nominal 860 mm span is not imposed as a chief-ray length.",
    f"The compressor input coupler, waveplate and ordinary half-inch CP_M1 mirror in POLARIS-K05VS2 are at Y={COMPRESSOR_INPUT_Y_MM:g} mm. CP_M1 is centered at (320, {COMPRESSOR_INPUT_Y_MM:g}, {COMPRESSOR_AXIS_HEIGHT_MM+COMPRESSOR_OFFSET_MM:g}) mm. The vertical roof entrance is at Y={COMPRESSOR_VERTICAL_ROOF_Y_MM:g} mm, between the grating and D pickoff, and its physical axis is offset {COMPRESSOR_VERTICAL_ROOF_TANGENT_OFFSET_MM:g} mm along local Y from the displaced return ray. The vertical roof is intentionally off axis; its revised integral stops are 2.54 mm above the seating floor. A PFD05-03-P01 in KM05DL remains at (320, {COMPRESSOR_PICKOFF_Y_MM:g}, {COMPRESSOR_AXIS_HEIGHT_MM-COMPRESSOR_OFFSET_MM:g}) mm, steering the fourth grating pass into SHG. The horizontal roof is entered through B first. Both straight-through beams are checked against the vertical roof with 1 mm radius probes, along with the pickoff and steering-mirror bypass checks.",
    f"One physical ST_G2 grating and one 25.4 mm ST_L2 lens in a POLARIS-L1G mount are each used four times. The lens focal length is 500 mm, its center is Z={LENS_AXIS_HEIGHT_MM:g} mm, and the upper/lower beams pass at Z={LENS_AXIS_HEIGHT_MM + BEAM_OFFSET_MM:g}/{LENS_AXIS_HEIGHT_MM - BEAM_OFFSET_MM:g} mm. The grating is centered at the lens axis height; its four passes are intentionally off axis.",
    "The upright 25.4 mm ST_Fold mirror in a POLARIS-K1VS2 mount lies 500 mm axially beyond the lens, at the original inter-grating midpoint for the default dimensions. Its normal follows the nominal telescope axis, not the sloping incident ray. The grating-to-lens gap remains 70 mm. Finite sloping ray lengths are computed rather than forced to the axial distance.",
    "The lower return traverses the same lens and grating, then a PFD05-03-P01 D-shaped mirror in a KM05DR mount selects it. The optical datum is 1 mm below the straight edge. The upper path clears the open half; a 1 mm radius clearance probe is checked against the optic and mount.",
    "The D pickoff is 75 mm before the grating. The VA100 is 75 mm after the pickoff, followed 75 mm later by the existing 25.4 mm ST_M1 retroreflector in a POLARIS-K1VS2 mount. The return retraces the entire folded path to the launching coupler.",
    f"The upper input steering mirror is 225 mm before the grating; the FBR half-wave plate is 150 mm before it. The integral-lens fiber coupler is 180 mm from that steering mirror. All starter distances and the {BEAM_OFFSET_MM:g} mm lens offset are editable in generate.py and the schematic poses.",
    "The plate top is Z=3 mm and thickness is 33 mm, preserving its underside at Z=-30 mm. Purchased mounts remain upright and use their real seats, recessed where required; no floating mounts or unspecified spacers are introduced.",
    "VA100 slit width is provisionally 1 mm. Beam waists and powers remain illustrative. Native and schematic traces use the existing ideal thin-lens, mirror and grating models; no detailed aberration, pulse dispersion, gain, SHG efficiency or phase matching is predicted.",
    "The output dichroic reflects 775 nm and transmits 1550 nm through an ideal 3 mm, n=1.5 plate. The exact coating/optic is unselected. The residual 1550 nm path retains its half-inch mirror and integral-lens coupler; fiber cables and the EDFA package are omitted.",
    "All delivered beam solids are constant-width center-ray guides. The plate and drilling are a provisional review draft.",
]


def documents():
    result = baseline.documents()
    result["stretcher"] = stretcher()
    result["compressor"] = compressor()
    result["output-775"] = lower_shg_output(result["output-775"])
    result["residual-1550"] = lower_shg_output(result["residual-1550"])
    return result


def generate(folder=None):
    folder = Path(folder or Path(__file__).parent)
    folder.mkdir(parents=True, exist_ok=True)
    for name, document in documents().items():
        compiled = compile_schematic(document)
        if not compiled.ok:
            raise ValueError([d.message for d in compiled.diagnostics])
        save_schematic(document, folder / (name + ".pyopticl-schematic.json"))
        (folder / (name + ".py")).write_text(compiled.source)
    (folder / "assumptions.json").write_text(json.dumps(ASSUMPTIONS, indent=2) + "\n")
    return folder


if __name__ == "__main__":
    generate()
