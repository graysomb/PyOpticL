"""Physical bounds and the CAD bridge can be checked without a FreeCAD install."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from itertools import product
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyOpticL import settings
from PyOpticL.bounds import BoundingCircleXY, BoundsUnavailable, component_circle_xy
from PyOpticL.schematic import compile_schematic, resolve_topology
from PyOpticL.schematic.bounds import BoundsProvider, compute_part_circle
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.registry import SYMBOLS
from test_schematic import branched, chain


def vector(x, y, z):
    return SimpleNamespace(x=x, y=y, z=z)


class Placement:
    """Small rigid-transform double; includes full 3D child rotations."""

    def __init__(self, translation=(0, 0, 0), rotation=((1, 0, 0), (0, 1, 0), (0, 0, 1))):
        self.translation, self.rotation = translation, rotation

    def multVec(self, point):
        values = (point.x, point.y, point.z)
        return vector(*(sum(a * b for a, b in zip(row, values)) + offset
                        for row, offset in zip(self.rotation, self.translation)))

    def __mul__(self, other):
        rotation = tuple(tuple(sum(self.rotation[i][k] * other.rotation[k][j] for k in range(3))
                               for j in range(3)) for i in range(3))
        translation = self.multVec(vector(*other.translation))
        return Placement((translation.x, translation.y, translation.z), rotation)


class Geometry:
    def __init__(self, ranges, facets=12):
        self.ranges, self.CountFacets = ranges, facets
        self.Placement = Placement()

    def copy(self):
        return deepcopy(self)

    def isNull(self):
        return False

    @property
    def BoundBox(self):
        points = [self.Placement.multVec(vector(*corner)) for corner in product(*self.ranges)]
        return SimpleNamespace(**{axis + suffix: func(getattr(point, axis.lower()) for point in points)
                                  for axis in "XYZ" for suffix, func in (("Min", min), ("Max", max))})


def component(label, geometry=None, children=(), mesh=False, placement=None):
    obj = SimpleNamespace(Label=label, Children=list(children), BasePlacement=placement or Placement(), Visibility=False)
    proxy = SimpleNamespace(get_object=lambda: obj)
    obj.Proxy = proxy
    if geometry is not None:
        if mesh:
            proxy.mesh = geometry
        else:
            proxy.shape = lambda: geometry
    proxy.drill = Mock(side_effect=AssertionError("Drill-clearance geometry must not be used"))
    return proxy


def circle(part, children=True):
    return component_circle_xy(part, Placement(), vector, children)


class GeometryBoundsTests(unittest.TestCase):
    def test_offset_mirror_body_is_bounded_about_optical_origin(self):
        part = component("mirror", Geometry(((-6, 0), (-6.35, 6.35), (-6.35, 6.35))))
        result = circle(part)
        self.assertAlmostEqual(result.radius_mm, math.hypot(6, 6.35))
        self.assertEqual(result.center_mm, (0, 0))
        self.assertEqual(result.diameter_mm, 2 * result.radius_mm)
        with self.assertRaises(FrozenInstanceError):
            result.radius_mm = 10
        part.drill.assert_not_called()

    def test_nested_assembly_transforms_and_invisible_hardware_are_included(self):
        bolt = component("bolt", Geometry(((-1, 1), (-1, 1), (-8, 8))),
                         placement=Placement((10, 0, 0), ((1, 0, 0), (0, 0, -1), (0, 1, 0))))
        mount = component("mount", children=[bolt.get_object()], placement=Placement((4, 0, 0)))
        part = component("optic", Geometry(((-1, 1), (-1, 1), (-1, 1))), [mount.get_object()])
        self.assertAlmostEqual(circle(part).radius_mm, math.hypot(15, 8))
        self.assertAlmostEqual(circle(part, children=False).radius_mm, math.sqrt(2))
        # Neither global placement nor geometry visibility changes a local bound.
        part.get_object().Placement = Placement((1000, 2000, 3000))
        self.assertAlmostEqual(circle(part).radius_mm, math.hypot(15, 8))

    def test_assembly_only_container_and_multiple_shapes(self):
        first = component("first", Geometry(((0, 1), (0, 2), (0, 3))))
        second = component("second", Geometry(((0, 6), (0, 8), (0, 1))))
        root = component("container", children=[first.get_object(), second.get_object()])
        self.assertEqual(circle(root).radius_mm, 10)
        part = component("compound")
        part.shape = lambda: [first.shape(), second.shape()]
        self.assertEqual(circle(part).radius_mm, 10)
        with self.assertRaises(BoundsUnavailable):
            circle(root, children=False)

    def test_mesh_copy_discards_display_placement_without_mutating_shared_mesh(self):
        mesh = Geometry(((-2, 2), (-3, 3), (-4, 4)))
        placement = mesh.Placement = Placement((1000, 2000, 0))
        part = component("mesh", mesh, mesh=True)
        self.assertAlmostEqual(circle(part).radius_mm, math.sqrt(13))
        self.assertIs(mesh.Placement, placement)
        self.assertEqual(mesh.Placement.translation, (1000, 2000, 0))
        self.assertAlmostEqual(circle(part).radius_mm, math.sqrt(13))

    def test_missing_child_geometry_fails_the_complete_assembly(self):
        missing = component("missing mount", Geometry(((0, 1), (0, 1), (0, 1)), facets=0), mesh=True)
        part = component("optic", Geometry(((0, 1), (0, 1), (0, 1))), [missing.get_object()])
        with self.assertRaisesRegex(BoundsUnavailable, "missing mount.*empty or missing"):
            circle(part)
        self.assertGreater(circle(part, children=False).radius_mm, 0)
        for bad in (None, [], Geometry(((float("nan"), 1), (0, 1), (0, 1)))):
            part = component("bad")
            part.shape = lambda bad=bad: bad
            with self.assertRaises(BoundsUnavailable):
                circle(part)

    def test_common_component_api_delegates_to_the_generic_geometry_walker(self):
        # Execute the actual method without importing the rest of CAD-backed layout.py.
        source = Path(__file__).resolve().parents[1] / "PyOpticL/layout.py"
        cls = next(item for item in ast.parse(source.read_text()).body
                   if isinstance(item, ast.ClassDef) and item.name == "Component")
        method = next(item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == "get_xy_bounding_circle")
        namespace = {"App": SimpleNamespace(Placement=Placement, Vector=vector)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        part = component("part", Geometry(((0, 3), (0, 4), (0, 5))))
        self.assertEqual(namespace[method.name](part).radius_mm, 5)

    def test_invalid_radius_and_cyclic_assembly_are_unavailable(self):
        for value in (0, -1, True, "1", float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                BoundingCircleXY(value)
        root = component("root", Geometry(((0, 1), (0, 1), (0, 1))))
        root.get_object().Children.append(root.get_object())
        with self.assertRaisesRegex(BoundsUnavailable, "cyclic"):
            circle(root)


class PartSpecTests(unittest.TestCase):
    def test_every_preset_uses_identical_factories_for_export_and_instantiation(self):
        def constructor(module, name):
            return lambda **kwargs: (module, name, kwargs)

        modules = {name: SimpleNamespace() for name in ("optics", "thorlabs")}
        for kind, symbol in SYMBOLS.items():
            for preset in symbol.presets:
                document = branched() if kind == "splitter" else chain("source", "stop")
                node = document.nodes[2] if kind == "splitter" else document.add_node(kind)
                node.preset = preset
                spec = part_spec(document, node, resolve_topology(document))
                if spec is None:
                    self.assertIn(kind, ("source", "output"))
                    continue
                def register(item):
                    setattr(modules[item.module], item.factory, constructor(item.module, item.factory))
                    for _, value in (*item.before, *item.after):
                        if hasattr(value, "factory"):
                            register(value)
                register(spec)
                with patch("PyOpticL.schematic.parts.import_module", side_effect=lambda name: modules[name.split(".")[-1]]):
                    actual = spec.instantiate()
                expected = eval(spec.render("parameters"), {**modules, "parameters": dict(spec.parameters)})
                self.assertEqual(actual, expected, (kind, preset))

    def test_settings_are_backward_compatible_and_do_not_change_export(self):
        document = branched()
        before = compile_schematic(document).source
        document.settings.update(show_bounds=True, bounds_scale=12)
        self.assertEqual(compile_schematic(document).source, before)
        older = document.to_dict()
        older["settings"].pop("show_bounds")
        older["settings"].pop("bounds_scale")
        loaded = document_from_dict(older)
        self.assertFalse(loaded.settings["show_bounds"])
        self.assertEqual(loaded.settings["bounds_scale"], 4)
        for key, value in (("show_bounds", 1), ("bounds_scale", 0), ("bounds_scale", float("nan"))):
            data = document.to_dict()
            data["settings"][key] = value
            with self.assertRaises(ValueError):
                document_from_dict(data)


class BoundsProviderTests(unittest.TestCase):
    def setUp(self):
        document = chain("source", "mirror", "stop")
        self.spec = part_spec(document, document.nodes[1], resolve_topology(document))

    def test_lazy_cache_refresh_and_geometry_settings(self):
        compute = Mock(return_value=BoundingCircleXY(12))
        provider = BoundsProvider(compute)
        self.assertIsNone(provider.peek(self.spec))
        compute.assert_not_called()
        self.assertEqual(provider.get(self.spec).circle.radius_mm, 12)
        self.assertEqual(provider.get(self.spec).circle.radius_mm, 12)
        self.assertEqual(compute.call_count, 1)
        original = settings.get_measurement_system()
        self.addCleanup(settings.set_measurement_system, original)
        settings.set_measurement_system("metric" if original == "imperial" else "imperial")
        self.assertIsNone(provider.peek(self.spec))
        provider.get(self.spec)
        self.assertEqual(compute.call_count, 2)
        provider.clear()
        provider.get(self.spec)
        self.assertEqual(compute.call_count, 3)

    def test_failed_or_incomplete_geometry_is_cached_as_unavailable(self):
        compute = Mock(side_effect=BoundsUnavailable("missing model"))
        provider = BoundsProvider(compute)
        result = provider.get(self.spec)
        self.assertIsNone(result.circle)
        self.assertIn("missing model", result.error)
        provider.get(self.spec)
        compute.assert_called_once()

    def test_temporary_document_cleanup_and_active_document_restoration(self):
        for existing in (False, True):
            for failure in (None, "definition", "component", "circle"):
                with self.subTest(existing=existing, failure=failure):
                    original = SimpleNamespace(Name="UserDesign") if existing else None
                    app = SimpleNamespace(ActiveDocument=original)
                    documents = {original.Name: original} if original else {}
                    def new_document(name):
                        self.assertEqual(set(documents), {original.Name} if original else set())
                        temporary = SimpleNamespace(Name=name)
                        documents[name] = temporary
                        app.ActiveDocument = temporary
                        return temporary
                    def close_document(name):
                        del documents[name]
                        app.ActiveDocument = None
                    def set_active(name):
                        app.ActiveDocument = documents.get(name)
                    app.newDocument, app.closeDocument, app.setActiveDocument = new_document, close_document, set_active
                    native_part = SimpleNamespace(get_xy_bounding_circle=Mock(return_value=BoundingCircleXY(8)))
                    if failure == "circle":
                        native_part.get_xy_bounding_circle.side_effect = RuntimeError("bounds failed")
                    spec = SimpleNamespace(instantiate=Mock(return_value=object()))
                    if failure == "definition":
                        spec.instantiate.side_effect = RuntimeError("definition failed")
                    constructor = Mock(return_value=native_part)
                    if failure == "component":
                        constructor.side_effect = RuntimeError("component failed")
                    with patch.dict("sys.modules", {"FreeCAD": app, "PyOpticL.layout": SimpleNamespace(Component=constructor)}):
                        if failure:
                            with self.assertRaises(RuntimeError):
                                compute_part_circle(spec)
                        else:
                            self.assertEqual(compute_part_circle(spec).radius_mm, 8)
                    self.assertIs(app.ActiveDocument, original)
                    self.assertEqual(set(documents), {original.Name} if original else set())


if __name__ == "__main__":
    unittest.main()
