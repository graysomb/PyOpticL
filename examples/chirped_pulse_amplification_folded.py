"""Build the independent folded CPA variant with FreeCAD's Python."""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.chirped_pulse_amplification import build as build_cpa
from PyOpticL.schematic import load_schematic
from PyOpticL import attachments, stages as translation_stages
import FreeCAD as App

SCHEMATICS = ROOT / "Designs/schematics/cpa-folded"
OUTPUT = ROOT / "artifacts/chirped_pulse_amplification_folded.FCStd"


def install_compressor_stage(root, sections, shared, components):
    """Keep the roof's reference pose; translate it along the roof/grating line."""
    roof = shared["CP_HRoof"]
    obj = roof.get_object()
    original = App.Placement(obj.Placement)
    support = next(part for part in attachments.descendants(obj)
                   if attachments.integration_profile(part.Proxy))
    profile = attachments.integration_profile(support.Proxy)
    seat_frame = next(frame for frame in support.Proxy.contract().frames
                      if frame.name == profile["seat_frame"])
    seat = support.Placement.multVec(App.Vector(*seat_frame.position))
    section = sections["compressor"]
    parent = section.get_object()
    local = parent.Placement.inverse() * original
    seat = parent.Placement.inverse().multVec(seat)

    adapter = translation_stages.AdapterSpec(
        thickness_mm=16, width_mm=100, depth_mm=70,
        platform_holes=("payload_1", "payload_2", "payload_7", "payload_8"),
        screw_length_mm=15.875,
    )
    motion = translation_stages.create("XR25C", "CP_HRoof XR25C stage")
    stage_yaw = local.Rotation.toEulerAngles("XYZ")[2] + 180
    rotation = App.Rotation(App.Vector(0, 0, 1), stage_yaw)
    # This adapter offset clears the detector bracket throughout the stroke.
    offset = (15., 0.)
    stack = App.Vector(*motion.spec.payload_frame.position)
    stack += App.Vector(*offset, adapter.thickness_mm)
    origin = seat - rotation.multVec(stack)
    parent.Children = [part for part in parent.Children if part != obj]
    obj.Parent = None
    section.add(motion, tuple(origin), stage_yaw)
    motion.mount_payload(roof, mounting_component=support, yaw=180,
                         offset=offset, adapter=adapter)
    root.recompute()
    if max(abs(a-b) for a,b in zip(original.toMatrix().A, obj.Placement.toMatrix().A)) > 1e-6:
        raise ValueError("Compressor stage installation changed zero-travel roof alignment")
    components[components.index(obj)] = motion.get_object()
    return {"CP_HRoof": motion}


def build(output=OUTPUT):
    output = Path(output)
    spec = importlib.util.spec_from_file_location(
        "cpa_folded_settings", SCHEMATICS / "generate.py"
    )
    settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings)
    shg_spacing = settings.validate_shg_spacing(
        {
            name: load_schematic(SCHEMATICS / (name + ".pyopticl-schematic.json"))
            for name in ("compressor", "output-775", "residual-1550")
        }
    )
    scene = build_cpa(
        output,
        schematic_folder=SCHEMATICS,
        plate_top_z=settings.PLATE_TOP_Z_MM,
        plate_thickness=settings.PLATE_THICKNESS_MM,
        baseplate_output=output.with_name(output.stem + "_baseplate.step"),
        install_hardware=install_compressor_stage,
    )
    scene.shg_spacing = shg_spacing
    return scene


if __name__ == "__main__":
    scene = build()
    print("Folded CPA saved:", OUTPUT, flush=True)
    print("SHG spacing:", scene.shg_spacing, flush=True)
    print("Pickoff clearance:", scene.report["stretcher_pickoff_clearance"], flush=True)
    print(
        "Stretcher:",
        {k: v for k, v in scene.report["routes"]["stretcher"].items() if k != "trace"},
        flush=True,
    )
