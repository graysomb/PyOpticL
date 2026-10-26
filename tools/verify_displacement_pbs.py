"""Compare the rebuilt PBS support against the pinned displacement center Body."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import FreeCAD as App
import Import
import Part
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import lab_catalog as catalog


def verify(source):
    measurement = json.loads((catalog.DATA / 'displacement_pbs_reference.json').read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest() != measurement['sha256']:
        raise ValueError('Displacement source revision differs from measured CAD')
    doc = App.newDocument('DisplacementReference')
    try:
        Import.insert(str(source.resolve()), doc.Name)
        bodies = [o for o in doc.Objects if o.Label == 'Body' and hasattr(o, 'Shape')]
        if len(bodies) != 1:
            raise ValueError('Expected exactly one center Body')
        reference = bodies[0].Shape.copy()
        reference.Placement = bodies[0].getGlobalPlacement()
        patch = measurement['patch']
        reference = reference.common(Part.makeBox(*patch['size'], App.Vector(*patch['origin'])))
        reference = catalog.transform(reference, measurement['optical_origin'])
        actual = catalog.DisplacementPBSHolder().shape()
        distances = []
        for a, b in ((reference, actual), (actual, reference)):
            points = a.tessellate(.05)[0]
            distances.extend(b.distToShape(Part.Vertex(p))[0]
                             for p in points[::max(1, len(points)//300)])
        result = dict(samples=len(distances), max_surface_deviation_mm=max(distances),
                      reference_volume_mm3=reference.Volume, generated_volume_mm3=actual.Volume,
                      passes_0_01_mm=max(distances) <= .01,
                      method='Bidirectional sampled surface distances; not exact Hausdorff distance')
        return result
    finally:
        App.closeDocument(doc.Name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.source)
    print(json.dumps(result, indent=2))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    if not result['passes_0_01_mm']:
        raise SystemExit(1)
