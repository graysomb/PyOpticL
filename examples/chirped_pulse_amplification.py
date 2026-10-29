"""Build the provisional CPA layout from four editable wavelength routes.

The layout is a review draft, not a validated pulse-amplification design.
Run with FreeCAD's Python. Dimensions, paths and assumptions are in
Designs/schematics/cpa; rerun its generate.py after changing starter values.
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import FreeCAD as App
import Part

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PyOpticL import attachments, lab_catalog, machined_baseplate
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamSegment, BeamPath, linear_polarization
from PyOpticL.schematic import compile_schematic, load_schematic
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.topology import resolve_topology

SCHEMATICS = ROOT / "Designs/schematics/cpa"


def compound(component):
    shapes = []
    for obj in (component, *attachments.descendants(component)):
        if (
            hasattr(obj, "Shape")
            and not obj.Shape.isNull()
            and getattr(obj.Proxy, "object_group", None) not in ("layout", "beam_path")
        ):
            shapes.append(obj.Shape)
    return Part.makeCompound(shapes)


def center_ray_shape(segment):
    """Render a guide without expensive Gaussian cone unions for a draft."""
    obj = segment.get_object()
    shape = Part.makeCylinder(
        0.4, segment.distance, App.Vector(), App.Vector(*segment.direction)
    )
    shape.Placement = obj.Placement
    obj.Shape = shape
    obj.Distance = segment.distance
    obj.Wavelength = App.Units.Quantity(f"{segment.wavelength} nm")
    obj.Power = App.Units.Quantity(f"{segment.power} W")
    q = segment.get_q_parameter()
    obj.InitialRadius = segment.get_beam_radius(q)
    obj.FinalRadius = segment.get_beam_radius(q + segment.distance)
    obj.purgeTouched()


def build(output=None, *, schematic_folder=SCHEMATICS, plate_top_z=0.0,
          plate_thickness=30.0, baseplate_output=None):
    # Restrict the display override to this build; the library tracer and its
    # Gaussian transport are unchanged. All delivered beam solids are guides.
    with patch.object(BeamSegment, "compute_shape", center_ray_shape):
        return _build(output, Path(schematic_folder), plate_top_z,
                      plate_thickness, baseplate_output)


def _build(output, schematic_folder, plate_top_z, plate_thickness, baseplate_output):
    source = App.newDocument("CPAStarterSource")
    root = Layout("CPA mechanical starter — provisional")
    stages, programs, components = {}, {}, []
    for name in ("stretcher", "compressor", "output-775"):
        document = load_schematic(schematic_folder / (name + ".pyopticl-schematic.json"))
        compiled = compile_schematic(document)
        if not compiled.ok:
            raise ValueError([item.message for item in compiled.diagnostics])
        namespace = {"__name__": "cpa_generated"}
        exec(compiled.source, namespace)
        stage = root.add(namespace["build_layout"](), (0, 0, 0), 0)
        stages[name], programs[name] = stage, namespace
        components.extend(
            o
            for o in stage.get_object().Children
            if getattr(o.Proxy, "object_group", None) != "beam_path"
        )
    # Reuse the output lens and dichroic physically; a second wavelength does
    # not add another copy of either optical assembly or another drill pattern.
    document = load_schematic(schematic_folder / "residual-1550.pyopticl-schematic.json")
    compiled = compile_schematic(document)
    if not compiled.ok:
        raise ValueError([item.message for item in compiled.diagnostics])
    ns = {"__name__": "cpa_generated"}
    exec(compiled.source, ns)
    shared = {o.Label: o.Proxy for o in components}
    for ref in ("SHG_L2", "SHG_M1"):
        position = ns["PLACEMENTS"][ref]
        obj = shared[ref].get_object()
        assert (obj.Placement.Base - App.Vector(*position[:3])).Length < 1e-6
    stage = root.add(Layout(document.title), (0, 0, 0), 0)
    topology = resolve_topology(document)
    for ref, position in ns["PLACEMENTS"].items():
        if ref in shared:
            continue
        node = document.node(ref)
        component = stage.add(
            Component(node.reference, part_spec(document, node, topology).instantiate()),
            position[:3], position[3],
        )
        components.append(component.get_object())
        shared[ref] = component
    settings = ns["SOURCE"]
    stage.add(BeamPath("SHG_1550_boundary", wavelength=settings["wavelength"],
        polarization=linear_polarization(settings["polarization_angle"]),
        power=settings["power"], waist=settings["waist"], bound_parent=root,
        final_distance=80, trace_limit=8, trace_ends=ns["OPEN_SEGMENTS"]),
        settings["position"], settings["angle"])
    stage.recompute()
    stages["residual-1550"], programs["residual-1550"] = stage, ns
    print("All four optical routes built and traced.", flush=True)
    plate, machining = machined_baseplate.add(
        root, position=(0, 0, plate_top_z), thickness=plate_thickness)
    root.recompute()
    print("Provisional baseplate machined.", flush=True)
    component_references = {o.Name: o.Label for o in components}

    def reference(obj):
        while obj is not None:
            if obj.Name in component_references:
                return component_references[obj.Name]
            obj = getattr(obj, "Parent", None)
        return None

    # Verify the full installation after nesting and plate machining as well.
    route_report = {}
    for name, stage in stages.items():
        objects = shared if name == "residual-1550" else {
            o.Label: o.Proxy
            for o in stage.get_object().Children
            if getattr(o.Proxy, "object_group", None) != "beam_path"
        }
        beam = next(
            o.Proxy for o in stage.get_object().Children if hasattr(o, "BeamSegments")
        )
        ns = programs[name]
        source_id = next(
            k for k, v in ns["EXPECTED_PASSES"].items() if v["mode"] == "emit"
        )
        check_pass_trace(beam, objects, ns["EXPECTED_PASSES"], source_id)
        route_report[name] = dict(
            passes=len(ns["EXPECTED_PASSES"]),
            ray_segments=len(beam.get_object().BeamSegments),
            wavelength_nm=beam.wavelength,
            actual_path_mm=sum(
                s.Proxy.distance for s in beam.get_object().BeamSegments
            ),
            trace=[dict(
                start_component=reference(s.StartObject),
                end_component=reference(s.EndObject),
                start_mm=list(s.Proxy.get_global_position()),
                end_mm=list(s.Proxy.get_global_position() + s.Proxy.distance * s.Proxy.get_global_direction()),
                direction=list(s.Proxy.get_global_direction()),
                internal=bool(s.InternalToComponent),
            ) for s in beam.get_object().BeamSegments],
        )

    # Check collisions between distinct physical optical assemblies. Internal
    # source contacts and nominal threaded envelopes are not cross-part clashes.
    bodies = [(o.Label, compound(o)) for o in components]
    bounds = [body.BoundBox for _, body in bodies]
    collisions = []
    for i, (label, shape) in enumerate(bodies):
        for j, (other, body) in enumerate(bodies[:i]):
            if bounds[i].intersect(bounds[j]):
                volume = shape.common(body).Volume
                if volume > 1e-5:
                    collisions.append(dict(a=label, b=other, volume_mm3=volume))
    print("Cross-assembly collision check complete.", flush=True)
    beam_collisions = []
    for stage_name, stage in stages.items():
        beam = next(
            o for o in stage.get_object().Children if hasattr(o, "BeamSegments")
        )
        for segment in beam.BeamSegments:
            allowed = set()
            for obj in (segment.StartObject, segment.EndObject):
                while obj is not None:
                    allowed.add(obj.Name)
                    obj = getattr(obj, "Parent", None)
            guide = Part.makeCylinder(
                0.1,
                segment.Proxy.distance,
                App.Vector(*segment.Proxy.get_global_position()),
                App.Vector(*segment.Proxy.get_global_direction()),
            )
            for (label, body), component, box in zip(bodies, components, bounds):
                if component.Name in allowed or not guide.BoundBox.intersect(box):
                    continue
                volume = guide.common(body).Volume
                if volume > 1e-5:
                    beam_collisions.append(
                        dict(
                            stage=stage_name,
                            segment=segment.Name,
                            unintended_component=label,
                            volume_mm3=volume,
                        )
                    )

    dichroic = shared["SHG_M1"].get_object()
    residual_beam = next(o for o in stages["residual-1550"].get_object().Children if hasattr(o, "BeamSegments"))
    rear = next(s for s in residual_beam.BeamSegments if s.StartObject == dichroic and not s.InternalToComponent)
    rear_guide = Part.makeCylinder(1, rear.Proxy.distance,
        App.Vector(*rear.Proxy.get_global_position()), App.Vector(*rear.Proxy.get_global_direction()))
    rear_overlap = sum(rear_guide.common(o.Shape).Volume for o in attachments.descendants(dichroic)
                       if hasattr(o, "Shape") and not o.Shape.isNull())
    if rear_overlap > 1e-5:
        raise ValueError("Dichroic mount obstructs the rear 1550 nm beam")

    pickoff_clearance = None
    if "ST_Pickoff" in shared:
        pickoff = shared["ST_Pickoff"].get_object()
        beam = next(o for o in stages["stretcher"].get_object().Children if hasattr(o, "BeamSegments"))
        upper = next(s for s in beam.BeamSegments
                     if reference(s.StartObject) == "ST_HWP1"
                     and reference(s.EndObject) == "ST_G2")
        guide = Part.makeCylinder(1, upper.Proxy.distance,
            App.Vector(*upper.Proxy.get_global_position()), App.Vector(*upper.Proxy.get_global_direction()))
        overlap = guide.common(compound(pickoff)).Volume
        pickoff_clearance = dict(probe_radius_mm=1, mount="KM05DR", overlap_mm3=overlap)
        if overlap > 1e-5:
            raise ValueError("D-shaped pickoff obstructs the upper stretcher beam")
    if collisions or beam_collisions:
        raise ValueError(dict(cross_assembly_collisions=collisions,
                              beam_to_unintended_component_collisions=beam_collisions))

    static = App.newDocument("CPAStarterReview")
    group = static.addObject("App::DocumentObjectGroup", "CPA_Starter")
    group.Label = "CPA — provisional dimensions and optical prescription"
    features, hardware = [], []
    lens_facings = []
    integrated = set(machining.integrated_names)
    for obj in attachments.descendants(root.get_object()):
        kind = getattr(obj.Proxy, "object_group", None)
        if (
            obj.Name in integrated
            or not hasattr(obj, "Shape")
            or obj.Shape.isNull()
            or kind == "layout"
            or (kind == "beam_path" and not hasattr(obj.Proxy, "distance"))
        ):
            continue
        feature = static.addObject("Part::Feature", obj.Name)
        feature.Label = obj.Label
        feature.Shape = obj.Shape.copy()
        is_beam = kind == "beam_path"
        if is_beam:
            # Constant-width center-ray guides avoid suggesting a validated
            # Gaussian envelope for this provisional optical prescription.
            feature.Shape = Part.makeCylinder(
                0.4,
                obj.Proxy.distance,
                App.Vector(*obj.Proxy.get_global_position()),
                App.Vector(*obj.Proxy.get_global_direction()),
            )
        color = (
            ((0.92, 0.12, 0.09) if obj.Proxy.wavelength == 1550 else (0.05, 0.42, 0.85))
            if is_beam
            else obj.Proxy.object_color
        )
        feature.addProperty("App::PropertyString", "DisplayColor")
        feature.DisplayColor = json.dumps(color)
        if feature.ViewObject:
            feature.ViewObject.ShapeColor = color
            feature.ViewObject.LineColor = (0.15, 0.17, 0.2)
            if is_beam:
                feature.ViewObject.Transparency = 30
        if hasattr(obj.Proxy, "contract"):
            feature.addProperty("App::PropertyString", "ComponentContract")
            feature.ComponentContract = json.dumps(
                obj.Proxy.contract().to_dict(), indent=2
            )
            feature.setEditorMode("ComponentContract", 1)
        if hasattr(obj.Proxy, "focal_length"):
            feature.addProperty("App::PropertyLength", "NominalFocalLength")
            feature.NominalFocalLength = obj.Proxy.focal_length
            feature.setEditorMode("NominalFocalLength", 1)
            direction = obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
            feature.addProperty("App::PropertyVector", "FacingDirection")
            feature.FacingDirection = direction
            feature.setEditorMode("FacingDirection", 1)
            lens_facings.append(dict(lens=obj.Label, direction=list(direction)))
            if obj.Label in ("ST_L1", "ST_L2", "SHG_L1", "SHG_L2"):
                # Visual assembly directions, excluded from hardware STEP/BOM
                # and all mechanical/beam collision checks.
                base = obj.Placement.Base + App.Vector(0, 0, 25)
                arrow = static.addObject("Part::Feature", obj.Label + "_Facing")
                arrow.Label = obj.Label + " facing (+X)"
                arrow.Shape = Part.makeCylinder(0.65, 24, base, direction).fuse(
                    Part.makeCone(2.3, 0, 6, base + direction * 24, direction)
                )
                arrow.addProperty("App::PropertyBool", "AnnotationOnly")
                arrow.AnnotationOnly = True
                arrow.addProperty("App::PropertyString", "DisplayColor")
                arrow.DisplayColor = json.dumps((0.0, 0.5, 0.4))
                if arrow.ViewObject:
                    arrow.ViewObject.ShapeColor = (0.0, 0.5, 0.4)
                features.append(arrow)
        if not is_beam:
            hardware.append(feature)
        features.append(feature)
    group.addObjects(features)
    report = dict(
        status="Provisional mechanical layout; optical prescription unconfirmed",
        assumptions=json.loads((schematic_folder / "assumptions.json").read_text()),
        routes=route_report,
        lens_facings=lens_facings,
        dichroic_rear_clearance=dict(probe_radius_mm=1, mount="MHV-12.7L-R", overlap_mm3=rear_overlap),
        stretcher_pickoff_clearance=pickoff_clearance,
        machining=machining.plan,
        cross_assembly_collisions=collisions,
        beam_to_unintended_component_collisions=beam_collisions,
        bom=[
            row
            for part in components
            for row in lab_catalog.bom(part.Proxy)
        ],
    )
    for name, value in (("ReviewReport", report), ("MachiningPlan", machining.plan)):
        group.addProperty("App::PropertyString", name)
        setattr(group, name, json.dumps(value, indent=2))
        group.setEditorMode(name, 1)
    static.recompute()
    output = Path(
        output or ROOT / "artifacts/chirped_pulse_amplification.FCStd"
    ).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    static.saveAs(str(output))
    Part.makeCompound([o.Shape for o in hardware]).exportStep(
        str(output.with_suffix(".step"))
    )
    plate_path = Path(baseplate_output or output.with_name("cpa_draft_baseplate.step")).resolve()
    plate_path.parent.mkdir(parents=True, exist_ok=True)
    plate.get_object().Shape.exportStep(str(plate_path))
    output.with_suffix(".review.json").write_text(json.dumps(report, indent=2) + "\n")
    output.with_suffix(".bom.json").write_text(json.dumps(report["bom"], indent=2) + "\n")
    output.with_suffix(".drilling.json").write_text(json.dumps(machining.plan, indent=2) + "\n")
    return SimpleNamespace(
        document=static,
        source=source,
        root=root,
        stages=stages,
        plate=plate,
        machining=machining,
        report=report,
    )


if __name__ == "__main__":
    scene = build()
    print(
        json.dumps(
            dict(
                routes=scene.report["routes"],
                collisions=scene.report["cross_assembly_collisions"],
                stock_bounds=scene.machining.plan["stock_bounds"],
            ),
            indent=2,
        )
    )
