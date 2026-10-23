# Reference measurements and verification

Measurements were taken from the supplied lab STEP files and exact Thorlabs STEP/drawing downloads before defining the corresponding nominal geometry. Machine-readable records and source hashes are in `PyOpticL/catalog_data/reference_measurements.json`; each vendor manifest pins its STEP or PDF independently. All comparisons use **0.01 mm and 0.01°**, not manufacturing tolerances.

## Vendor references

| Part | Official drawing document | Drawing revision | Measured native datums (mm) |
|---|---|---|---|
| POLARIS-K05VS2 | POLARIS-K05VS2-E0W | C | Optic contact plane Z=2.159; mounting face Y=-12.7; post-hole axis at X=0, Z=8.96484066 |
| F260FC-1550 | 7524-E0W | D | Barrel front Z=9.5504; axis X=Y=0; FC/PC end Z=-14.1732 |
| AD1109F | 13080-E0W | B | M11 seating shoulder Z=0.762; SM05 shoulder Z=-3.937; nose end Z=-7.112 |
| KA05TA | KA05TA-E0W | A | Bore axis X=9.09394, Y=14.67817; front seat Z=2.39919; base Y=1.97817; post-hole axial coordinate Z=18.68338 |
| ELL16 | ELL16-E0W | A | Optical axis native Y; cage mounting plane Y=-8.64876292; four hole axes at X/Z=±15 |
| XR25C | XR25C-E0W | E | Base Y=-7.112; payload Y=15.888; native translation axis X; payload height 23 |

Source pages: [POLARIS-K05VS2](https://www.thorlabs.com/item/POLARIS-K05VS2), [F260FC-1550](https://www.thorlabs.com/item/F260FC-1550), [AD1109F](https://www.thorlabs.com/item/AD1109F), [KA05TA](https://www.thorlabs.com/item/KA05TA), [ELL16](https://www.thorlabs.com/item/ELL16), [XR25C](https://www.thorlabs.com/item/XR25C).

The optical collimator reference is a barrel-front datum, not a claimed lens principal plane. Vendor cylinder origins are not necessarily their end faces: axial projections were used for hole-center comparisons. Hole records distinguish drawing thread standards from modeled bore diameters. XR25C records all 22 payload-hole axes and their 1/4-20 specification. Mounting slots and partial holes should be interpreted through their reference profiles, not replaced by arbitrary circular holes.

Normalization maps vendor coordinates to component coordinates while retaining original source bytes. Optics face local +X. ELL16's mounting face is placed at holder X=10; the holder wall ends at X=13. The XR25C payload frame is local Z=23. DOF ranges remain unknown instead of inferring symmetric travel from total-travel marketing specifications.

## Coupling chain

The [collimator compatibility table](https://www.thorlabs.com/fixed-focus-collimation-packages-fcpc-connectors?tabName=Overview) and exact drawings identify F260FC-1550 → AD1109F → KA05TA. The first mate is external/internal M11 × 0.5; the second is external/internal SM05 (0.535-40). The adapter's M9 thread is not used.

The user selected **the end of the M11 thread** as the nominal placement datum. Vendor STEP plane Z=6.5532 is 2.9972 mm behind the collimator front at Z=9.5504. The AD1109F opening is aligned with that thread-end plane. The model does not bottom the collimator against the adapter's inner shoulder; its 6.35 mm threaded depth is not used as the insertion distance.

With the collimator front at assembly X=0, the adapter opening is X=-2.9972 and its SM05 shoulder is X=8.0518. KA05TA's front is X=8.0518. The contract records the user-selected nominal convention and its measured CAD datum.

The SM05 section is 3.175 mm long and its shoulder is seated against the mount. A direct solid-pair check of the initially installed front retaining ring found 58.885 mm³ interference with the adapter, so that ring is removed and retained as an unused included BOM item. The rear ring remains installed. Internal adjusters are not split into moving bodies.

At the delivered thread-end placement, individual-solid boolean checks report **0 mm³ overlap and no unresolved operations** for collimator/adapter, collimator/mount and adapter/mount. Results are recorded in `coupling_interference.json`; `tools/check_catalog_interference.py` reproduces the check. Checking individual solids is necessary because a compound-level result can hide an internal accessory collision.

FC/APC is rejected as an equivalent FC/PC connector. Nominal geometry and mechanical interface standards are checked separately from optical suitability, coupling efficiency, tightening torque and physical installation access.

## HOM custom parts

The source assembly labels are `PBSClipBottom`, `Body`, and `Part 1` (ELL16 holder). The reconstruction stores rational sketch curves rather than opaque reference solids. Thicknesses, extrusions, holes and rounded upright edges are constructed parametrically.

- PBS seat: global Z=44.45; cube center Z=50.8; raised seating pads end at Z=47.45.
- PBS clamp: 5 mm extrusion, bottom Z=44.45; diagonal 3 mm slot retained.
- PBS clamp tap drill: center (-14.52157288, 9.52157288), Ø2.5, straight depth 5 mm, drill tip ending at Z=38.69892. Thread specification M3 × 0.5.
- PBS support comparison region: box from (-25,-15,25.4) with dimensions (40,40,24.6). This is a patch of the integral base and carries no invented standalone attachment holes.
- ELL16 holder: base Z=25.4, 7 mm thick; upright Y=-28.1 to -25.1; optical center (0,-38.1,50.8). Cage slots centered at X=±15, Z=35.8/65.8; base mounting slots X=±25.25; locating features X=-10,0,10 at Y=-38.1.

Bidirectional sampled surface checks against independently imported solids:

| Part | Samples | Maximum sampled deviation |
|---|---:|---:|
| PBS clamp | 560 | 1.02 × 10⁻¹³ mm |
| PBS support patch | 635 | 4.23 × 10⁻⁶ mm |
| ELL16 holder | 512 | 1.79 × 10⁻⁸ mm |

These are sampled comparisons, not a proof of the full continuous Hausdorff distance. The source uses spline surfaces even for planar/extruded features; integrated volume differs slightly after analytic reconstruction (notably about 2.96 mm³ on the 10,431 mm³ rotation holder). Surface locations, seats and hole/slot datums are the acceptance measures. Raw results are in `hom_verification.json`.

Generic M3 × 8 and 4-40 × 3/16-inch screws are explicit nominal fastening selections, not recovered vendor part numbers. Their nominal engagement is respectively 3 mm and 1.7625 mm. Manufacturer-specific head geometry and procurement selection remain unverified. External baseplate attachment hardware is not included.

## SPDC support decision

**Not verified compatible; excluded from the coupling preset.** The pinned `OutMount_BeamPathR_Machine (1).step` has a measured row at X=11.56, Y=-18.6 through -167.4 on 12.4 mm spacing, top Z=25.4, with Ø5.1054 modeled bores. KA05TA's mounting clearance is Ø4.6228 for #8/M4. The STEP alone does not establish a suitable thread, bolt, washer or adapter stack. The matching beam-line labels in the SPDC assembly are optical paths, not coupling supports. No unsupported compatibility claim is made from those labels or approximate diameters.

## Verification boundary

The automated suite passed 15 tests (7 standard-Python and 8 FreeCAD 1.1.4 integration tests). It checks FreeCAD construction, pinned solids, independently measured vendor hole axes, nominal frames, DOF transforms, read-only summaries, metadata inertness, repeat recomputation, instance isolation and an existing mirror/interfaces/drill workflow. Downloader tests cover malformed files, hash changes, identity errors, both vendor-domain handlers and dynamic-page fallback. Skills pass the skill validator; their known-chain and mismatch logic is exercised through the connection API.

No physical motion, motor control, optical coupling-efficiency test, complete sweep of the historic example scripts, or physical assembly test is claimed. OptoSigma public-link handling is tested with fixtures; no OptoSigma part is needed by these five catalog entries. The SPDC fastening stack and manufacturer-specific external fasteners remain open procurement/installation qualification items. The coupling nominal placement follows the explicitly selected thread-end convention.
