"""Compare parametric holders to independently imported lab CAD.

Supply a directory containing reference BREP exports named Part__Feature009,
Part__Feature267 and pbs_support (see reference report for extraction bounds).
These are validation inputs only, never runtime geometry dependencies.
"""
import argparse
import json
from pathlib import Path
import sys
import FreeCAD as App
import Part
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyOpticL import lab_catalog as catalog


def verify(directory):
    results={}
    for kind,filename,origin,rotation in [
        ('pbs-clamp','Part__Feature009',(0,0,50.8),(0,0,0)),
        ('pbs-holder','pbs_support',(0,0,50.8),(0,0,0)),
        ('rotation-holder','Part__Feature267',(0,-38.1,50.8),(0,0,-90))]:
        ref=Part.Shape();ref.read(str(directory/(filename+'.brep')))
        ref=catalog.transform(ref,origin,rotation)
        actual=catalog.HOMHolder(kind).shape()
        distances=[]
        for a,b in [(ref,actual),(actual,ref)]:
            points=a.tessellate(.05)[0]
            sampled=points[::max(1,len(points)//250)]
            distances.extend(b.distToShape(Part.Vertex(point))[0] for point in sampled)
        maximum=max(distances)
        results[kind]={'samples':len(distances),'max_surface_deviation_mm':maximum,
                       'reference_volume_mm3':ref.Volume,'generated_volume_mm3':actual.Volume,
                       'passes_0_01_mm':maximum<=.01}
        print(kind,results[kind],flush=True)
    return results

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference_directory',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    results=verify(args.reference_directory)
    if args.output:args.output.write_text(json.dumps(results,indent=2)+'\n')
    if not all(r['passes_0_01_mm'] for r in results.values()):raise SystemExit(1)
