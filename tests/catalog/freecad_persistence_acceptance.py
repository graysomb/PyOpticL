"""Native datum and schematic-definition persistence for editable assemblies."""
from pathlib import Path
import sys,unittest
import FreeCAD as App
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PyOpticL import cad_persistence
from PyOpticL.schematic import load_schematic
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.topology import resolve_topology


class PersistenceTests(unittest.TestCase):
    def test_nested_cad_datums_roundtrip(self):
        original=dict(vector=App.Vector(3,-5,7),rotation=App.Rotation('XYZ',-90,17,133),
                      placement=App.Placement(App.Vector(21,-13,9),App.Rotation('XYZ',12,-31,67)))
        clone=cad_persistence.loads(cad_persistence.dumps(original))
        self.assertLess((clone['vector']-original['vector']).Length,1e-12)
        self.assertLess((clone['rotation'].multVec(original['vector'])-
                         original['rotation'].multVec(original['vector'])).Length,1e-12)
        self.assertLess((clone['placement'].multVec(original['vector'])-
                         original['placement'].multVec(original['vector'])).Length,1e-12)

    def test_bare_grating_definition_roundtrip(self):
        from PyOpticL.schematic.catalog_parts import grating
        original=grating(mounted=False,mirrored=True)
        clone=cad_persistence.loads(cad_persistence.dumps(original))
        self.assertEqual(clone.surface_angle,original.surface_angle)
        self.assertEqual(clone.order,original.order)
        self.assertAlmostEqual(clone.shape().Volume,original.shape().Volume,places=8)
        self.assertEqual(type(clone.interfaces()[0]),type(original.interfaces()[0]))

    def test_complete_folded_catalog_definitions_roundtrip(self):
        folder=Path(__file__).resolve().parents[2]/'Designs/schematics/cpa-folded'
        count=0
        for path in folder.glob('*.pyopticl-schematic.json'):
            document=load_schematic(path);topology=resolve_topology(document)
            for node in document.nodes:
                specification=part_spec(document,node,topology)
                if specification is None:continue
                with self.subTest(route=path.stem,part=node.reference):
                    original=specification.instantiate()
                    clone=cad_persistence.loads(cad_persistence.dumps(original))
                    self.assertIs(type(clone),type(original))
                    if hasattr(original,'contract'):
                        self.assertEqual(clone.contract().to_dict(),original.contract().to_dict())
                    if hasattr(original,'interfaces'):
                        self.assertEqual([type(i) for i in clone.interfaces()],
                                         [type(i) for i in original.interfaces()])
                    count+=1
        self.assertGreaterEqual(count,31)


if __name__=='__main__':unittest.main(verbosity=2)
