"""Build the independent folded CPA variant with FreeCAD's Python."""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.chirped_pulse_amplification import build as build_cpa

SCHEMATICS = ROOT / "Designs/schematics/cpa-folded"
OUTPUT = ROOT / "artifacts/chirped_pulse_amplification_folded.FCStd"


def build(output=OUTPUT):
    output = Path(output)
    spec = importlib.util.spec_from_file_location(
        "cpa_folded_settings", SCHEMATICS / "generate.py"
    )
    settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings)
    return build_cpa(
        output,
        schematic_folder=SCHEMATICS,
        plate_top_z=settings.PLATE_TOP_Z_MM,
        plate_thickness=settings.PLATE_THICKNESS_MM,
        baseplate_output=output.with_name(output.stem + "_baseplate.step"),
    )


if __name__ == "__main__":
    scene = build()
    print("Folded CPA saved:", OUTPUT, flush=True)
    print("Pickoff clearance:", scene.report["stretcher_pickoff_clearance"], flush=True)
    print(
        "Stretcher:",
        {k: v for k, v in scene.report["routes"]["stretcher"].items() if k != "trace"},
        flush=True,
    )
