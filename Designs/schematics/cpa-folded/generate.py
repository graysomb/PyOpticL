"""Separate folded CPA variant; run to regenerate its editable routes and scripts.

The baseline CPA generator supplies the unchanged compressor and SHG routes.
No baseline schematic or artifact is overwritten by this generator.
"""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from PyOpticL.ray_math import add, mul, yaw
from PyOpticL.schematic import Connection, Endpoint, compile_schematic, save_schematic
from PyOpticL.schematic.model import OpticalPass

spec = importlib.util.spec_from_file_location(
    "cpa_baseline", ROOT / "Designs/schematics/cpa/generate.py"
)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)

LENS_AXIS_HEIGHT_MM = 12.7
BEAM_OFFSET_MM = 2.0
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


ASSUMPTIONS = [
    "Separate folded CPA variant. The baseline CPA files and artifacts are retained; compressor, SHG and rear 1550 nm collection routes are unchanged.",
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
