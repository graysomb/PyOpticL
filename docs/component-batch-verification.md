# Vendor component batch verification

Verified 2026-10-26 with FreeCAD's bundled Python on this Mac. Backlog items
2–6 and 8 are implemented at their native heights. The
[LightSmyth grating and MK05S assembly](grating.md) was delivered separately,
with direct grating seating, a native-height plate adapter and diffraction wrapper.
HRS1015-P01 was delivered separately with its
[two-orientation integral supports and explicit optical path](roof-mirror.md).

## Delivered behavior

| Selection | Native height, mm | Height on plate, mm | Plate operations |
|---|---:|---:|---|
| POLARIS-L05G | 12.7 | 12.7 | 1 M4 + 2 dowels |
| POLARIS-L1G | 19.05 | 19.05 | 1 M4 + 2 dowels |
| POLARIS-K1VS2 mirror | 25.4 | 25.4 | 1 M4 + 2 dowels |
| MHV-12.7L-R mirror | 12.7 | 12.7 | 2 M4 + 2 dowels |
| MHV-25.4L-R mirror | 25.4 | 25.4 | 3 M4 + 2 dowels |
| FBR waveplate | 14.3002 | 14.3002 | 2 receiving bores for included 1/8-inch pins |
| VA100 slit and bracket | 17.78 | 27.78 | 2 M4 |
| POLARIS-K05T6 coupling | 12.7 | 12.7 | 1 M4 + 2 dowels |

Eight exact STEP assets and eight drawings are hash-pinned in
`PyOpticL/catalog_data/assets/`. Independent datums, volumes and hole/slot
measurements are in `batch_measurements.json`; working normalization and mating
plate profiles are separate records. Source assets were acquired from the
manufacturers' public product downloads. None were unavailable.

Purchased geometry retains source dimensions and holes. Configuration changes
are limited to removing the K05T6 front ring for the adapter and positioning
FBR's supplied ring against its waveplate. Original cached bytes remain intact.

Shared attachment operations drive ordinary `Baseplate` and `MachinedBaseplate`
including nested transforms. Component-hole contracts remain distinct from plate
operations. Mixed-height plans have per-mount height maps and a null legacy
scalar; uniform layouts retain a scalar. The contract serialization schema and
original vendor profile file are unchanged.

## Automated results

| Suite | Passing tests |
|---|---:|
| Standard-Python catalog/download/contract tests | 7 |
| Existing FreeCAD catalog acceptance | 10 |
| Existing FreeCAD baseplate acceptance (explicit legacy KA05TA) | 4 |
| Existing fixed-iris acceptance | 10 |
| Batch acceptance, including review export/reopen | 8 |
| **Total** | **39** |

Batch acceptance checks source hashes, imported solids, native heights, seating,
source cylindrical axes and slot arcs, mirror size/reflection, FBR retaining-ring
contact and Jones polarization, slit width/orientation, contract roundtrips,
BOM accessory disposition and instance isolation. Physical plate cuts cover all
25 operations in both workflows, translated/rotated nested assemblies, moving a
component, and repeated recomputation without duplicated features or holes.
Legacy KA05TA retains its screw-only pattern and its existing seating checks.

`examples/component_batch.py`, `examples/lab_catalog_demo.py` and
`examples/two_mirror_coupling.py` rebuilt successfully. The two-mirror route is
120 → 100 → 120 mm, with four M4 and eight dowel operations.

The batch FreeCAD review contains eight groups, 26 static part features,
147 solids, contracts and BOMs. It reopens with valid shapes and no Python
proxies. Its STEP roundtrip also contains 147 valid solids. Bounding limits
agree within 0.01 mm; volume differs by 0.21958 mm³ across approximately
551162 mm³ (0.40 ppm), below the 1 ppm export acceptance threshold. This small
integration difference arises when imported spline geometry is serialized.

## Review files and reproduction

Generated files are local artifacts, excluded from Git:

- `artifacts/component_batch.FCStd`: all eight assemblies and drilled samples,
  with read-only contracts, BOMs and machining plans.
- `artifacts/component_batch.step`: complete solid assembly.
- `artifacts/component_batch.report.json`: source evidence, height contributions,
  contracts, machining operations, BOMs and qualifications.
- `artifacts/component_batch.verification.json`: export checks and suite counts.
- `artifacts/component_batch.png`: same-scale CAD overview at native heights.

```bash
python3 -m unittest discover -s tests/catalog -p 'test_*.py' -v
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_acceptance.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_baseplate_acceptance.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_iris_acceptance.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_component_batch_acceptance.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python examples/component_batch.py
```

The example rebuilds the editable source in a live document before exporting a
static review. Runtime reconstruction requires the hash-matching asset cache;
the saved review and STEP do not.

## Fit and modeling qualifications

- **VA100:** optical `slit_width` spans 0–6 mm; mechanical solids stay at the
  supplier's 5.8928 mm reference opening. Translating blades alone produces
  housing interference, so articulated blade/linkage motion is not claimed.
  The 10 mm bracket, screw access and nominal engagement are checked at that
  reference pose. Install its underside 8-32 screw before mounting to the plate.
- **K05T6/AD1109F:** simplified SM05 envelopes overlap approximately 4.08248 mm³
  within the nominal thread engagement annulus only. No interference is accepted
  outside it. Shoulder seating, retaining-ring removal, nominal thread standards
  and collimator clearance pass; physical thread phase, torque and fit under
  load remain unverified. The older zero-overlap result applies to KA05TA.
- **FBR:** its included Ø3.175 mm pins require different bores from the 2 mm lab
  convention. The chosen Ø3.20 × 5 mm receiving bores provide nominal clearance;
  no vendor receiving-fit tolerance is available.
- **MHV:** the selected 2 × 5 mm pins leave 0.555 mm nominal engagement in the
  measured blind features. Mating plate tolerances are identified as a custom
  selection. The 12.7 mm source has a small pose deviation producing roughly
  0.00036 mm³ nominal mirror contact overlap, within the 0.01 mm/0.01° source
  comparison boundary. Source solids are preserved.
- Plate fasteners use M4 threads with nominal tap-drill geometry. Installation
  screw lengths for purchased mounts remain requirements in their BOMs;
  manufacturer-specific external screw/head selection is not inferred from CAD.
  VA100 includes explicit nominal screws for its designed bracket stack.

These checks qualify nominal CAD, propagation and drilling behavior. They do
not constitute a physical assembly or manufacturing-fit test.
