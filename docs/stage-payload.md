# Linear stages and receiving-part attachments

`PyOpticL.stages` provides an opt-in stage assembly with an explicit machining
receiver. The existing static `lab_catalog.create('translation', ...)` preset
keeps its previous behavior. The folded CPA example explicitly installs one XR25C
below CP_HRoof; the unfolded CPA design remains unchanged.

```python
from PyOpticL import stages, lab_catalog, machined_baseplate
from PyOpticL.layout import Layout

root = Layout('Stage setup')
stage = root.add(stages.create('XR25C', travel_limits=(-12.5, 12.5)),
                 (0, 0, 0), 0)
mirror = lab_catalog.create('mirror', 'Moving mirror', mount='POLARIS-K05VS2')
adapter = stage.mount_payload(
    mirror, yaw=135, offset=(0, 0),
    adapter=stages.AdapterSpec(
        thickness_mm=16, width_mm=100, depth_mm=70,
        platform_holes=('payload_1', 'payload_2', 'payload_7', 'payload_8'),
        screw_length_mm=15.875))
plate, machining = machined_baseplate.add(root, thickness=20)
root.recompute()
stage.set_travel(5)
```

## Placement and motion

The stage origin remains at its fixed reference. `Travel` is an editable FreeCAD
Distance property in millimeters, along the declared axis in stage coordinates.
For XR25C, zero reproduces the pinned centered source pose and the available
range is -12.5 to +12.5 mm, as explicitly marked in drawing E. The platform is
23 mm above the base seat. `TravelLimits` can narrow, but cannot enlarge, the
verified interval. Changing travel recomputes payload placement and invalidates
native ray segments before tracing again.

`offset=(x,y)` specifies the selected mount's seating datum in the adapter plane;
`yaw` rotates the payload about that datum. Adapter thickness and the selected
mount's real seat determine optical height. No implicit spacer or optical-height
correction is added. Choose `mounting_component=` explicitly when a payload has
more than one eligible mount. One adapter assembly per stage is supported; an
assembly may contain multiple mounts if all are supported by that adapter.
Declared integral supports can also be payloads: their stock patches and clamp
bores become part of the adapter, using the same receiver boundary. They are
excluded from separate hardware exports and remain marked as integral in the BOM.
Stacked stages, schematic stage editing and motor control are outside this version.

`LinearStageSpec` holds mounting/payload frames, a normalized translation axis,
reference position and limits without importing FreeCAD. `StageDefinition`
provides the fixed/moving shapes, fixed mounting contract/profile and payload
hole contract. `LinearStage(..., definition=...)` uses the same motion and
attachment implementation for other declared stages. The current `AdapterSpec`
fastener configuration supports existing top-face 1/4-20 platform holes.
Descriptive component DOFs remain inert; motion comes from the stage proxy.

## Machining ownership

`attachments.set_target(component, receiver)` sets an explicit `AttachmentTarget`
on a subtree. `receiving_part()` resolves its nearest boundary. Without one,
profile operations retain their existing baseplate destination. The same resolver
is used by `MachinedBaseplate` and the ordinary library `Baseplate`, including
legacy drilling fallback and integral-support traversal.

The purchased stage base supplies four selected 1/4-20 baseplate taps through its
actual open slots. Payload screw/dowel bores and hardware reliefs belong to the
fabricated adapter. They never continue through to the underlying baseplate.
Changing travel changes world placement, not local machining coordinates.

The example adapter is 100 x 70 x 16 mm. Four existing platform holes receive
1/4-20 x 5/8-inch cap screws through 6.8 mm clearance bores and 10.5 mm x 6.5 mm
top counterbores. Nominal platform engagement is 6.375 mm in the documented
7.6 mm thread depth. The stage base selects the same screw length with 1.6 mm
washers (6.8 mm ID, 12.7 mm OD): 8.56 mm nominal plate engagement beneath the 5.715 mm slot head seat.
The mirror's existing M4 tap and two locating-pin bores are machined in the
adapter. Threads are represented by drilling geometry and metadata.

Adapters check hole edge distances, intersecting cuts, drill-tip stock,
platform thread depth, top screw access and planar mount-seat support.
Manufacturing geometry includes conservative per-body bounding-box sweeps over
the **whole configured interval**, with access allowances from mount profiles.
This can reserve more space than an exact swept solid. `validate_clearance()`
checks those envelopes against external hardware and the machined baseplate;
intentional internal rail/bearing contacts are excluded. Base screw, washer and
head clearance is additionally checked with exact capsule sweeps over the
continuous interval. Hex access is checked with a 2.5 mm-radius tool at opposite
hardware stroke endpoints, before the payload is installed.

## Vendor evidence and limits

`catalog_data/xr25c_stage_reference.json` pins the drawing/STEP hashes, four slot
centers/radii and every source solid's volume/bounds. The base slots are open
slots, not invented circular mounting holes. The carriage group includes its
platform, contact pad, lock screw, upper rails, fasteners, rail end stops and
micrometer stem/thimble with its end cap. The stem translates with the contact
pad; its barrel and clamp stay fixed.
The remaining vendor solids retain their nominal pose. At zero, the two groups
reproduce the original 61-solid vendor compound without geometry edits.

This is a rigid-carriage geometric model. Springs, rolling elements and internal
micrometer rotation are not simulated or used to infer mechanical performance.
The original source asset remains unchanged. New source hashes require body and
mounting revalidation.

## Example and verification

Run with FreeCAD's Python and its library directory on `PYTHONPATH`:

```sh
python examples/translation_stage_payload.py
python tests/catalog/freecad_stage_acceptance.py
```

The example traces a 1550 nm beam to a moving mirror and a receiver plane. It
exports a live FCStd, an assembly STEP, separate baseplate/adapter STEP files,
a receiver-keyed drilling report, a BOM and a full-travel clearance report under
`artifacts/translation_stage_payload*`. Reopening the editable FCStd requires
this checkout on FreeCAD's Python import path. `Travel` and attachment links
persist; the document is not flattened to static CAD.

## Folded CPA horizontal roof

`examples/chirped_pulse_amplification_folded.py` explicitly mounts CP_HRoof on
one XR25C. At zero travel the original roof pose, all four grating spots and
all other optics are unchanged. The stage axis follows the roof/grating line; positive travel moves toward
the grating. The stage is reversed beneath the roof and the roof's adapter
seat is offset 15 mm along the stage axis to clear the detector throughout
the full stroke. The 100 x 70 x 16 mm adapter contains the existing horizontal
roof supports and M2 clamp tap. Its seating slab is 16 mm thick and the
integral stops rise another 2.54 mm, requiring at least 18.54 mm billet height
before machining. Its four platform selections and screws match
the example above. No purchased stage or roof body is drilled.

The stage base sits at Z=-39 mm. The plate remains at Z=3 mm on top and
uses 60 mm slab stock (underside Z=-57 mm) to support this recess and its
12 mm blind base taps. Full configured travel is reserved in the recess.
The fixed stage declares `recess_by_solid`: each vendor body supplies a
separate pocket so empty space beside the micrometer remains stock supporting
the nearby detector bracket. Both baseplate workflows honor this contract.
The standard FCStd is the static review; the `_live.FCStd` companion preserves
`CP_HRoof XR25C stage.Travel`. The `.receivers.json` report separates the
baseplate from the moving adapter, which has its own STEP export.
