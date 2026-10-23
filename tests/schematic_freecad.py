"""Run inside FreeCAD's Python console:

    exec(open('/path/to/PyOpticL/tests/schematic_freecad.py').read())

Creates and closes its own test documents; existing designs are preserved.
"""

import unittest
import FreeCAD as App

from PyOpticL.schematic import Connection, Schematic, compile_schematic
from PyOpticL.schematic.model import new_id


def chain(*kinds):
    document = Schematic()
    nodes = [document.add_node(kind) for kind in kinds]
    for source, target in zip(nodes, nodes[1:]):
        document.connections.append(Connection(new_id(), source.id, "out", target.id))
    return document


def branched(nested=False):
    document = chain("source", "lens", "splitter")
    splitter = document.nodes[-1]
    for port, kind in (("transmitted", "fiber_output"), ("reflected", "splitter" if nested else "stop")):
        target = document.add_node(kind)
        document.connections.append(Connection(new_id(), splitter.id, port, target.id))
    if nested:
        splitter = document.nodes[-1]
        for port, kind in (("transmitted", "stop"), ("reflected", "output")):
            target = document.add_node(kind)
            document.connections.append(Connection(new_id(), splitter.id, port, target.id))
    return document


class FreeCADSchematicTests(unittest.TestCase):
    def setUp(self):
        self.previous = App.ActiveDocument.Name if App.ActiveDocument else None
        self.cad = App.newDocument("SchematicIntegrationTest")

    def tearDown(self):
        App.closeDocument(self.cad.Name)
        if self.previous:
            App.setActiveDocument(self.previous)

    def build(self, document, change=None):
        result = compile_schematic(document)
        self.assertTrue(result.ok, [diagnostic.message for diagnostic in result.diagnostics])
        namespace = {"__name__": "schematic_integration"}
        exec(compile(result.source, "schematic_generated.py", "exec"), namespace)
        if change:
            change(namespace)
        return namespace["build_layout"]()

    def test_lens_iris_chain(self):
        self.build(chain("source", "lens", "iris", "stop"))

    def test_counterclockwise_mirror(self):
        document = chain("source", "mirror", "stop")
        document.nodes[1].physical["turn"] = 90
        self.build(document)

    def test_clockwise_mirror(self):
        document = chain("source", "mirror", "stop")
        document.nodes[1].physical["turn"] = -90
        self.build(document)

    def test_splitter(self):
        self.build(branched())

    def test_nested_splitters(self):
        self.build(branched(nested=True))

    def test_fiber_source_waveplates_and_fiber_output(self):
        self.build(chain("fiber_source", "hwp", "qwp", "fiber_output"))

    def test_open_output(self):
        self.build(chain("source", "output"))

    def test_rotated_source(self):
        document = chain("source", "mirror", "stop")
        document.nodes[0].physical.update(x=20, y=30, angle=45)
        self.build(document)

    def test_accidental_interception_reports_part_references(self):
        document = chain("source", "lens", "stop")
        def change(namespace):
            namespace["PLACEMENTS"]["D1"] = (25, 0, 180)
        with self.assertRaisesRegex(RuntimeError, "Missing:.*L1"):
            self.build(document, change)


def run():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FreeCADSchematicTests)
    return unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == "__main__":
    run()
