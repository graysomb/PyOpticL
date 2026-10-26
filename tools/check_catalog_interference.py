"""Check individual nominal solids; distinguish unresolved booleans from clearance.

Threaded fastener envelopes intentionally overlap tapped holes and are excluded.
This is not a physical assembly or thread engagement qualification.
"""
import argparse
import json
from pathlib import Path
import sys
import FreeCAD as App
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyOpticL import lab_catalog as catalog


def check(kind):
    document=App.newDocument('Interference_'+kind)
    assembly=catalog.create(kind,kind);assembly.recompute()
    objects=[o for o in document.Objects if hasattr(o,'Shape') and not o.Shape.isNull()
             and o.Shape.Solids and o.Proxy.object_group!='fasteners']
    result={}
    for i,left in enumerate(objects):
        for right in objects[i+1:]:
            volume=0.;errors=[]
            for ai,a in enumerate(left.Shape.Solids):
                for bi,b in enumerate(right.Shape.Solids):
                    if not a.BoundBox.intersect(b.BoundBox) or a.distToShape(b)[0]>1e-7:continue
                    try:
                        overlap=a.common((b,),1e-6)
                        if not overlap.isNull():volume+=overlap.Volume
                    except (ValueError,RuntimeError) as error:
                        errors.append({'left_solid':ai,'right_solid':bi,'error':str(error)})
            key=left.Label+'/'+right.Label
            result[key]={'overlap_mm3':volume,'unresolved_booleans':errors}
            print(kind,key,result[key],flush=True)
    App.closeDocument(document.Name)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assemblies',nargs='+',default=['coupling'],choices=catalog.CATALOG_IDS)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result={kind:check(kind) for kind in args.assemblies}
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')

    if any(row['unresolved_booleans'] or row['overlap_mm3']>1e-4 for assembly in result.values() for row in assembly.values()):
        raise SystemExit(1)
