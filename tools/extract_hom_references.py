"""Extract independently located HOM reference parts for geometry regression."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import FreeCAD as App
import Import
import Part
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyOpticL.lab_catalog import DATA

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path,help='Data/HOM Mount/HOM setup.step')
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    expected=json.loads((DATA/'reference_measurements.json').read_text())['source_files']['../Data/HOM Mount/HOM setup.step']
    if hashlib.sha256(args.source.read_bytes()).hexdigest()!=expected:
        raise ValueError('Lab source differs from independently measured revision')
    args.output.mkdir(parents=True,exist_ok=True)
    doc=App.newDocument('HOMReference')
    Import.insert(str(args.source.resolve()),doc.Name)
    selected={}
    for obj in doc.Objects:
        if hasattr(obj,'Shape') and obj.Shape.Solids and obj.Label in ('Part 1','PBSClipBottom','Body'):
            if obj.Label in selected:raise ValueError('Ambiguous reference label: '+obj.Label)
            shape=obj.Shape.copy();shape.Placement=obj.getGlobalPlacement()
            selected[obj.Label]=shape
    selected['Part 1'].exportBrep(str(args.output/'Part__Feature267.brep'))
    selected['PBSClipBottom'].exportBrep(str(args.output/'Part__Feature009.brep'))
    # The PBS supports are integral to the large base. Compare an explicitly
    # bounded patch, not an invented stand-alone holder attachment pattern.
    selected['Body'].common(Part.makeBox(40,40,24.6,App.Vector(-25,-15,25.4))).exportBrep(str(args.output/'pbs_support.brep'))
    print('Extracted three references from the pinned HOM source.')
