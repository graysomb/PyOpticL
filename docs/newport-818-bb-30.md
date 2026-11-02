# Newport 818-BB-30 detector and mounting bracket

In the schematic editor, add **Photodetector (Newport 818-BB-30)** and choose
**818-BB-30 + baseplate bracket** or **818-BB-30, bare** under **Part preset**.
The bracket defaults to a 25.4 mm optical height above its mounting face;
**Bracket beam height** accepts values of 25.4 mm or greater. This changes the
bracket, not the optical position or the purchased housing. Set the optical Z
position separately when building a layout in Python.

```python
from PyOpticL import lab_catalog as catalog

mounted = catalog.create('photodetector', 'PD1', optical_height=25.4)
bare = catalog.create('818-BB-30', 'Bare detector')
bracket = catalog.definition('818-BB-30-bracket', optical_height=25.4)
```

The [example](../examples/newport_detector.py) builds a complete plate-mounted
assembly and alignment ray. It writes a FreeCAD document, separate bracket STEP,
and JSON contracts/machining plan under `artifacts/newport-818-bb-30.*`.
The exported STEP uses assembly coordinates, with the bracket bottom at Z=0;
the JSON records the transform from its optical-frame contract to that STEP.

## Purchased detector

The original, single-solid STEP comes from the exact
[Newport product page](https://www.newport.com/p/818-BB-30), using its Drawings & CAD
dialog and STEP download. Both that source and the exact product drawing are
bundled with SHA-256 manifests. No similar detector or replacement envelope is
substituted. Normalization only translates and rotates a working copy.

The optical origin is the external entrance-bore center, with local +X outward
and +Z upright. Internal photosensitive axial depth is not dimensioned and is
not inferred. The detector terminates a nominal ray within the 0.10 mm active
diameter and 20 degree acceptance half-angle. This is a geometric receiver model:
it does not calculate photocurrent, clipping loss, bandwidth response or damage.
The documented wavelength range is 800–1750 nm.

The purchased-part contract describes the M4 and 8-32 bottom holes and the BNC
interface. Inch-derived STEP dimensions control normalization; the drawing's
rounded 17.18 mm optical height differs from the CAD's 17.1958 mm by 0.0158 mm.
Independent native dimensions, bore positions/depths, source hashes and the
normalization are recorded in
[`newport_818_bb_30_reference.json`](../PyOpticL/catalog_data/newport_818_bb_30_reference.json).

## Bracket and drill contract

The fabricated adapter has a raised housing seat, two clearance registration
lips and an 8 mm foot. It retains the detector through the existing M4 bottom
hole using a nominal M4 × 6 socket screw, inserted from underneath before the
bracket is installed on the plate. Its counterbore leaves a 4 mm clamped web.
The lips have 0.2 mm housing clearance; they limit gross rotation and are not
claimed as precision registration of the purchased detector.

Two M4 × 12 socket screws attach the foot to the baseplate. Each counterbore
leaves a 4 mm foot web and gives nominal 8 mm plate engagement. The two 2 × 5 mm
locating pins register the bracket, following the existing catalog convention:
4.445 mm in the plate and 0.555 mm projecting into the bracket's blind holes.
The modeled BNC and housing clear the bracket and plate-screw driver access.

`ComponentContract.holes` describes the bracket's own M4 clearance/counterbores
and blind locating bores. `baseplate_profile()` / `attachments.operations()`
describe the mating plate instead:

- Two M4 × 0.7 taps: 3.3 mm drill diameter, 10 mm straight drill depth,
  8 mm thread depth, plus the standard 118 degree drill tip.
- Two locating bores: 2.01 mm nominal diameter, 4.445 mm straight depth,
  with the catalog's diameter limits and depth tolerance.

Both ordinary `Baseplate` drilling and `machined_baseplate` consume the same
contract. Coordinates follow the full assembly and nested placement transforms;
recomputing rebuilds from stock rather than accumulating cuts. Bare detectors
have no fabricated baseplate profile.

For recessed installations, the pocket follows the bracket axes and adds 50% to its
total transverse width by extending only local +Y, the BNC side. The opposite
wall, both axial walls, floor and attachment positions remain fixed. With the
default 0.25 mm machining clearance, the recess is 46.5 mm along local X and
96.75 mm across Y, rather than 64.5 mm across Y, adding 32.25 mm on the BNC side.
The drilling report records
`recess_side_scale_xy: {"y_plus": 1.5}` and the rotated pocket origin/dimensions.

**Before fabrication:** the drawing does not state usable thread depth in the
detector. The source CAD's smooth minor-diameter bores have 2.54 mm straight
depth. The selected detector screw inserts nominally 2 mm, but usable thread
depth and retention must be checked on the physical unit. Threads and socket
hardware use nominal clearance envelopes rather than a pinned fastener model.

## Verification

Portable/editor checks: `tests/test_schematic_detector.py`.
Native CAD, contact/clearance, ray, drilling and persistence checks:
`tests/catalog/freecad_newport_detector_acceptance.py`.
