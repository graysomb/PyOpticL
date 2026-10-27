<div align="center">

<img width="300" src="https://github.com/user-attachments/assets/6abdeee1-0d27-4417-b13f-469ae00388c7">

<br>

<img width="300" alt="PyOpticL" src="https://github.com/user-attachments/assets/385d672c-ae25-4efd-be92-cdcde1c0254b" />

### Code-to-CAD Optical Engineering

Design optical systems in Python and automatically generate modular CAD models of optical hardware.

<p>
  <a href="https://quantum-journal.org/papers/q-2026-06-15-2135/">
    <img src="https://img.shields.io/badge/Quantum-2026-blue" alt="Quantum Paper">
  </a>
  <a href="https://github.com/UMassIonTrappers/PyOpticL/releases">
    <img src="https://img.shields.io/github/v/release/UMassIonTrappers/PyOpticL" alt="Release">
  </a>
	<a href="https://discord.gg/vV4NP6rXmp">
	  <img src="https://img.shields.io/badge/Discord-Join%20Discord-5865F2?logo=discord&logoColor=white" alt="Discord">
	</a>
	<a href="https://github.com/UMassIonTrappers/PyOpticL/wiki/Quick-Start">
  <img src="https://img.shields.io/badge/Get%20Started-Quick%20Start-success" alt="Quick Start">
</a>
	  <a href="https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-%E2%80%90-ECDL-with-Isolation-Baseplate">
    <img src="https://img.shields.io/badge/DIY-LASER-red" alt="ECDL Baseplate">
  </a>
</p>

[Publication](https://quantum-journal.org/papers/q-2026-06-15-2135/) •
[Examples](#modular-baseplate-examples) •
[Quick Start](https://github.com/UMassIonTrappers/PyOpticL/wiki/Quick-Start) •
[Discord](https://discord.gg/vV4NP6rXmp)

[Lab catalog and component contracts](docs/lab-catalog.md) · [Reference measurement report](docs/reference-measurements.md)

The lab catalog's [original CAD sources](PyOpticL/catalog_data/sources/README.md)
are included in Git. A complete checkout rebuilds offline without a personal CAD
cache; run `python3 -m PyOpticL.vendor_cad verify --all` to check every source pin.

</div>

<!-- <img height="100" alt="PyOpticL_logo" src="https://github.com/user-attachments/assets/6abdeee1-0d27-4417-b13f-469ae00388c7" /> -->

PyOpticL (Python Optics Layout) is a Python library for code-to-CAD design of optical systems using modular baseplates. It places optics along simulated beam paths, including branched beam paths, so routing is automatic and dynamic as optics are added or modified. Baseplates are designed to be easily machined or 3D printed and mounted on an optical table. Baseplates are easy to set up as aligning optics on the baseplate is like 'paint by numbers', with each optic having a pre-aligned mount. Baseplates are reusable building blocks that can be combined into modular subsystems. Subsystems are also reusable at various wavelengths such that they can be easily combined into many different experimental apparatuses. 

If you use PyOpticL in your research, please cite our paper published in Quantum. The paper introduces PyOpticL and demonstrates its use in a trapped-ion quantum computing experiment, including laser cooling, state detection, and high-fidelity qubit operations.

<img width="700" alt="banner" src="https://github.com/user-attachments/assets/725264e8-112d-42e8-a89b-91602258fd7d" />

## What can I design and build with PyOpticL?

- [Laser Pulse Control Systems](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-‐-Doublepass-Baseplate)
- [Extended-Cavity Diode Lasers (ECDLs)](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-%E2%80%90-ECDL-with-Isolation-Baseplate)
- [Saturation Absorption Spectroscopy](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-%E2%80%90-Saturation-Absorption-Spectroscopy-Baseplate)
- [Qubit Laser Systems](https://github.com/UMassIonTrappers/PyOpticL/wiki/Subsystem-%E2%80%90-Raman)
- [Neutral Atom Quantum Computer](https://github.com/hybrid-lab/PyOpticL_Rubidium_System)
- [Trapped Ion Quantum Computer](https://github.com/UMassIonTrappers/PyOpticL/wiki/Apparatus-%E2%80%90-Trapped-Ions-%E2%80%90-Strontium)

## Code Structure

```python
baseplate = Component(...)
beam = baseplate.add(BeamPath(...))

beam.add(mirror())
beam.add(waveplate())
beam.add(beamsplitter_cube())
```

### Optical schematic editor

The workbench includes **New Optical Schematic** and **Open Optical Schematic**.
The canvas now shows physical optical geometry in millimetres. **Export Python…**
creates an ordinary PyOpticL macro and checks its actual ray trace when it runs.
**Generate CAD…** validates the current schematic, builds its full assembly in a
new FreeCAD document, checks the actual ray trace, and saves both the selected
`.FCStd` file and its companion `.py`. The 3D assembly opens with the view fitted
to the parts. Each generation uses a separate document; existing designs are
preserved. Save the schematic separately to retain its editable constraints.
**Baseplate** is enabled by default for both exports. It sizes a rectangular
machined plate around the hardware with a 15 mm edge margin and 12.7 mm thickness.
Click the blank canvas to change **Plate thickness** and **Plate edge margin**.
Supported lab-catalog mounting presets supply the screw holes, dowel holes and
integral supports. Unsupported or bare optics require a mounted preset or turning
off **Baseplate**; attachment holes are never inferred for those parts.

- Place a part from the palette and select its **Part preset** and optical
  parameters in the inspector. Each physical optic has one shared position,
  orientation and body outline, sized from its optical element. Mounts remain
  part of the assembly rather than inflating the optical body symbol.
- Click free ports to connect explicit optical passes. A/B connections are
  reversible; propagation is inferred from one source. Crossings do not connect
  rays or create visits. Physical beam segments are straight; turns require an optic.
- To send a return beam through an existing lens, waveplate, mirror or splitter,
  select that component and click **Add pass**. Select the desired **Optical pass**
  before wiring it, or right-click the body to choose a pass and port. The physical
  part is created only once in Python. Removing an extra pass keeps its component.
  The visit graph must be finite and acyclic; it may revisit physical components.
- Switch the **XY / XZ** control to inspect the same 3D geometry. Horizontal roofs
  displace the return sideways; vertical roofs displace it in height. Returning
  rays can traverse the same lens and waveplate before reaching an explicit pickoff.
  Finite apertures, single-sided coatings, off-axis lens deflection and roof facets
  are checked. An unintended interception reports the part and beam and asks you
  to add a pass or move the optic.
- In a valid layout, drag a body to solve its new placement while preserving hard
  constraints. A valid release is one undoable edit; an unresolved release restores
  the previous layout and reports residuals. If the layout already has errors or missing
  connections, dragging and **R** keep edits as an undoable draft while respecting
  position and source-direction pins. Dashed connection guides and ports stay at
  the component bodies so incomplete layouts remain easy to reconnect. Validation
  and CAD generation still require a resolved optical layout.
  **R** requests a yaw rotation. Free geometry changes
  without checking any constraint boxes. Grid coordinates and sizes use millimetres.
  When connecting or moving a centered mirror, its starting orientation is
  calculated from the two beam legs, including a turn to the coated face when
  needed. Position, direction and turn constraints still apply.
- Half-wave plates and irises automatically align their optical axis with the
  beam for straight-through transmission. Their body faces perpendicular to
  the beam, from either propagation direction. A half-wave plate's **Fast axis**
  parameter still sets its polarization rotation independently of its body yaw.
- **Centered hit** is enabled by default for each component's primary pass and
  for fiber receivers and roof entrance ports. **Add pass** starts additional
  passes through a shared optic with centering off, so a roof's displaced return
  can hit a different point on the same physical part. Enable it explicitly for
  a coaxial return that must use the same center.
  Dragging and optimization keep the ray at the optic's nominal interaction center
  in both transverse directions when centering is enabled. Existing saved
  constraints are preserved: clear **Centered hit** on an older return pass if
  it conflicts with a displaced return. Clear-aperture checks still apply;
  reduce roof beam separation or select a larger optic if the return misses it.
  A roof's center refers to
  its entrance port; its internal geometry retains the displaced exit.
  Its **Beam separation** fixes the actual transverse return offset. Dragging
  adjusts the roof's free angle to preserve that offset; a position pin fixes
  only X/Y.
- The placement grid has **Snap to grid** enabled by default and an editable
  **Grid** spacing in millimetres beside the XY/XZ selector. Snapping applies
  when adding or dragging parts; it adds no position, angle or distance
  constraints. Optical solving can move free parts off the grid. Changing
  spacing or disabling snap leaves existing parts in place.
- **Constrain position** pins the shared component origin in X/Y. Every visit
  uses that same pose. **Constrain beam length** pins the distance between its
  optical interaction points. Free lengths and free orientations can adjust.
- Select a mirror or splitter and the relevant **Optical pass**, then enable
  **Constrain angle**. This pins the signed change in travel direction in XY:
  +90° is counterclockwise, −90° clockwise. All passes share the same optic yaw;
  incompatible per-pass requests cannot be satisfied independently. Splitter
  transmission remains straight. Uncheck the box to leave the turn free.
- Sources offer **Constrain source direction**. Open outputs, stops and fiber
  receivers offer **Constrain output direction** for the arriving travel heading
  in XY. Fiber receivers automatically turn to face the arriving beam even with
  this box unchecked; checking it fixes the travel heading as well. A returning
  visit to a source fiber can receive on the same assembly.
- **Path lengths…** constrains the total geometric distance along a unique route,
  including across splitter branches and between two passes of the same part.
  Roof internal air paths are included; refractive-index weighting is not used.
  **Add / update path** automatically moves free components to satisfy the
  target and refreshes the measured length and status in the dialog. **OK**
  applies the positions and constraints as one undoable edit; **Cancel** discards
  them. Conflicting pinned positions or distances remain explicit errors.
  The dialog also highlights the route. Renaming
  references preserves constraints; deleting an endpoint removes its constraints.
- **Part bounds**, off by default, shows conservative full-assembly XY circles
  at the same millimetre scale as the canvas. These include mounts, adapters and
  hidden hardware. **Refresh bounds** clears the geometry cache. The inspector
  shows radius/diameter or the reason bounds are unavailable. XY bounds are hidden
  in the XZ view. Circle overlaps are conservative indicators, not CAD collision tests.
- **Validate** lists local redundancy warnings and unresolved constraint errors.
  Redundant, satisfied equations do not block export. Contradictory explicit
  length equations are identified separately from numerical residuals. The status
  shows locally free degrees of freedom. Incomplete or inconsistent drafts remain saveable.

The merged lab catalog is available through **Part preset**, including POLARIS/MHV
mirror mounts, POLARIS lens mounts, FBR/ELL16 waveplate mounts, fiber assemblies,
PBS, alignment iris, slit, grating and roof presets. See the
[catalog guide](docs/schematic-catalog.md) for parameters and vendor CAD cache setup.
Some symbols mark only the known optical aperture; their inspectors say so rather
than inventing a vendor body size. Physical packing still requires complete assembly bounds.

**Optimize physical layout…** fits the current physical system into an XY rectangle.
The dialog resolves assembly geometry on the GUI thread, then runs an immutable
numerical snapshot in a cancellable worker. The independent preview shows assembly
disks, beam capsules and violations. Defaults are 1 mm clearance and 1 mm beam
keep-out diameter. Differing heights do not exempt parts from conservative XY packing.
The region starts at current extents plus 10 mm, or the previous applied rectangle.

**Run** uses damped force-directed motion, constraint projection and deterministic
multi-start search. Pins, explicit lengths, selected-pass turns and source/output
headings remain hard constraints. Native-like optical relationships, finite
apertures and declared visits are rechecked before a result can be applied.
Bounds must be available for every physical part. Beam crossings are allowed;
unrelated assemblies must clear each capsule. Gaussian beam envelopes and exact
CAD collision detection are outside the packing model.

Enable **Allow folding** on individual original beams to permit generated mirrors.
A constrained original beam still pins its endpoint separation; a path constraint
controls its routed length. The inspector shows both. Schematic mirrors default
to **Turning** and are retained. **Folding** mirrors may be omitted unless protected
by a position/angle constraint, incident fixed length, path endpoint or use by
multiple optical passes. Generated mirrors are marked as added; omitted parts are
listed in the inspector and have no fabricated physical position.

The search defaults to mounted 12.7 mm mirrors, at most four added per original
beam and eight overall. Candidates share each start's 5,000-iteration budget and
20 projection passes, in 200-iteration batches. It tries both sides of stressed
spans, keeps infeasible intermediate candidates, and explores occupied mirror-count
groups fairly. Removal defaults to interior angles above 110° (180° is straight),
with 10° hysteresis and a 200-iteration cooldown. Verified feasible results prefer
fewer Folding mirrors, then lower normalized spring energy.

**Apply** updates physical geometry in one undoable edit and preserves all explicit
constraint boxes. Export creates retained parts and added mirrors once each,
omits bypassed mirrors, and verifies the ordered finite pass trace and final
open-beam lengths. **Cancel** leaves the document unchanged. **Clear optimized
layout** restores the pre-optimization physical poses. Numerical exhaustion says
**No feasible layout found**, with remaining violations; it does not prove impossibility.

Changes to topology, pass assignments, physical poses, parts, constraints or packing
settings make an applied solution stale and block export until rerun or cleared.
Reference renames, projection changes and display settings preserve it. Stale
snapshots remain saveable and undoable. Version 6 stores shared parts, explicit
passes and physical poses. Versions 1–5 migrate on load without rewriting the
original file: valid existing physical geometry is used as the initial pose,
decorative bends are removed with a conversion note, and older applied optimizations
remain stale until rerun or cleared. Unresolved legacy drafts receive editable
estimated poses. Existing explicit source directions and constraints are preserved.

[Shared-optic examples](Designs/schematics/multipass/) include horizontal and vertical
lens/waveplate returns with pickoffs, plus a two-fold packing example that keeps
60 mm endpoint separation and a 180 mm routed path. They include editable documents,
Python exports, actual editor screenshots and separate numerical/native verification
reports. Reproduce them with:

```sh
QT_QPA_PLATFORM=offscreen python Designs/schematics/multipass/generate.py --render
```

The folding example uses explicitly analytical assembly disks. Native checks in
`tests/schematic_multipass_freecad.py` verify exported interactions and total air
path; the recorded roof tests use an analytical body fixture to exercise native
finite interfaces independently of the vendor body geometry. Earlier
[version 5 optimization examples](Designs/schematics/optimization/) remain historical
fixtures and require rerunning or clearing their saved optimization after migration.

Open [the branched example](Designs/schematics/branched.pyopticl-schematic.json)
to try a mirror, lens, beamsplitter, fiber output, and beam stop. Its
[exported Python](Designs/schematics/branched.py) demonstrates the generated code.
Run exported `.py` files using the same FreeCAD macro workflow as existing
designs. The script builds a `Layout`, places parts, computes a `BeamPath`, and
checks the resulting optical connections. Refine its `PLACEMENTS` (mm/degrees),
`EXPECTED_PASSES`, and `SOURCE` dictionaries as needed. Changes to those dictionaries
are explicit: moving the source does not automatically relocate the other parts.
Regeneration replaces exported Python; Python edits do not update the schematic.

The current model supports one emitting source with finite branches and explicit
shared-component visits, including displaced returns. Multiple independent sources,
beam merging, automatic recirculating cavities, AOM routing, nonrectangular packing
regions and fabrication constraints remain outside this editor.

The document model and compiler can also be used without FreeCAD:

```python
from PyOpticL.schematic import load_schematic, compile_schematic

schematic = load_schematic("branched.pyopticl-schematic.json")
result = compile_schematic(schematic)
if result.ok:
    with open("branched.py", "w", encoding="utf-8") as stream:
        stream.write(result.source)
else:
    for diagnostic in result.diagnostics:
        print(diagnostic.message)
```

Run core tests with `python -m unittest discover -s tests -p 'test_schematic*.py'`.
Editor tests run when a Qt binding is available and otherwise skip. They can run
with `QT_QPA_PLATFORM=offscreen`; FreeCAD supplies Qt for normal workbench use.
For actual CAD/beam integration tests, execute
`tests/schematic_freecad.py` inside FreeCAD. That test suite creates and closes
its own documents and preserves existing designs.

Every CAD `Component` exposes `get_xy_bounding_circle(include_children=True)`.
It returns an immutable `BoundingCircleXY` with `center_mm == (0, 0)`,
`radius_mm`, and `diameter_mm`, in the component's local XY plane. Set
`include_children=False` to bound only its own body. Missing physical geometry
raises `PyOpticL.bounds.BoundsUnavailable`; visibility and drilling-clearance
envelopes do not affect the result.

The portable connection API uses unordered endpoints, for example
`Connection(id, Endpoint(lens_id, "B"), Endpoint(source_id, "beam"))`.
Set `connection.length = 75` for a 75 mm constraint, or `None` to use the default.
Set `connection.allow_folding = True` to permit physical mirror insertion, and
`mirror.mirror_role = "folding"` to make a schematic mirror eligible for removal.
Add `PathLengthConstraint(id, component_a_id, component_b_id, length_mm)` to
`schematic.path_constraints` for a hard total routed length. The pure numerical
API is `optimize_layout(problem, options=None, progress=None, cancelled=None)`;
`build_problem` consumes pre-resolved part radii and the added-mirror radius,
and callbacks run on the calling worker thread without CAD operations.
`resolve_topology(schematic)` returns source-oriented connections, incident
ports, interaction roles, and diagnostics without modifying the document.
`document.add_pass(component_id)` adds an explicit visit. Use
`Endpoint(component_id, port_id, pass_id)` for its connections; an empty pass ID
addresses the primary visit. `PathLengthConstraint` accepts optional `pass_a` and
`pass_b` endpoint identities. `document.layout["poses"]` stores shared XYZ/yaw free
values, and `solve_scene` is the CAD-independent constrained scene solver.


### Used by researchers at:

MIT • Stanford • [UC Berkeley](https://github.com/hybrid-lab/PyOpticL_Rubidium_System) • [UMass Amherst](https://websites.umass.edu/rniffenegger/pyopticl-code-to-cad-optical-layout/) • [UW Madison](https://github.com/hybrid-lab/PyOpticL_Rubidium_System) • UConn • NUS • Quera • [Harvard](https://github.com/hybrid-lab/PyOpticL_Rubidium_System) • [CalvinQ](https://github.com/hybrid-lab/PyOpticL_Rubidium_System)

## Readme contents:
 
* [Installation](#getting-setup)
* [Quick start](https://github.com/UMassIonTrappers/PyOpticL/wiki/Quick-Start)
* [Publication](#publication--high-fidelity-trapped-ion-qubit-operations-with-pyopticl)
* [Wiki](#wiki)
* [Baseplate Examples](#modular-baseplate-examples)
* [Subsystem Examples](#modular-subsystems-based-on-baseplates)
* [Apparatus Examples](#apparatus-based-on-modular-subsystems)
* [PyOpticL Community](https://github.com/UMassIonTrappers/PyOpticL/tree/main#pyopticl-community)

---


## Publication – High-Fidelity Trapped-Ion Qubit Operations with PyOpticL

<a href="https://quantum-journal.org/papers/q-2026-06-15-2135/">
    <img width="500" src="https://github.com/user-attachments/assets/4f8e2af5-2d51-4a9c-bdf8-13fc257014b8" />
</a>

We use PyOpticL in our trapped ion laboratory at UMass Amherst to design modular optical systems for trapped-ion quantum computing. In this paper we demonstrate laser cooling, state detection, and >99% fidelity single-qubit gates in our trapped-ion system using PyOpticL baseplates and lasers.

### Read the paper

- **Quantum (2026):**  
  [Qubit operations using a modular optical system engineered with PyOpticL: a code-to-CAD optical layout tool](https://quantum-journal.org/papers/q-2026-06-15-2135/)

- **arXiv preprint:**  
  [arXiv:2501.14957](https://arxiv.org/abs/2501.14957)

### Citation

Please cite our paper if you use PyOpticL. Thank you! 

> Myers, J., Caron, C., Helaly, N., Wei, Z., Oh, J., Gotobed, Z., Yabe, K., & Niffenegger, R. J.  
> *Qubit operations using a modular optical system engineered with PyOpticL: a code-to-CAD optical layout tool*.  
> Quantum **10**, 2135 (2026).


### [UMass Amherst Trapped Ion system built with PyOpticL](https://websites.umass.edu/rniffenegger/pyopticl-code-to-cad-optical-layout/):

<a href="https://github.com/UMassIonTrappers/PyOpticL/wiki/Apparatus-%E2%80%90-Trapped-Ions-%E2%80%90-Strontium">
	<img width="700" alt="UMass Amherst Trapped Ions" src="https://github.com/user-attachments/assets/2b61827e-5624-4590-b8a4-2e94640a9535" />
</a>

<img width="700" src="https://github.com/user-attachments/assets/b24b1d63-7b17-4de1-95dd-dcf176b8d9d6" width=400>


### Modular abstraction: Optics → Baseplates → Subsystems → Apparatus:
<img width="700" alt="Abstraction" src="https://github.com/user-attachments/assets/1b857ff6-a425-4261-a6f4-b00795de6f05" />

---

## Getting Setup

1. **Install FreeCAD, Python, and Git**

2. **Add PyOpticL as a custom addon repository in FreeCAD**  
	Under _Edit>Preferences>Addon Manager>Custom Repositories,_ click the plus icon and enter the following information: \
    _Repository URL:_ https://github.com/UMassIonTrappers/PyOpticL.git \
    _Branch:_ main \
   Press _OK_ to save settings

4. **Install the PyOpticL library**
    In the Addon Manager _(Tools>Addon Manager),_ search for "PyOpticL" and click install. \
   _Note: if you get an error related to git, try disabling it - Edit>Preferences>Addon Manager>Disable git_
		
6. **Check everything is setup correctly**  
   You should now be able to re-launch FreeCAD and see the "PyOpticL" workbench in the workbench dropdown
   <!-- <img width="250" alt="Screenshot 2023-10-27 225345" src="https://github.com/user-attachments/assets/7a43cac3-7d3b-4a3b-8e5f-189f39729251"> -->

7. **Check out the [wiki](https://github.com/UMassIonTrappers/PyOpticL/wiki) for guides on how to [get started](https://github.com/UMassIonTrappers/PyOpticL/wiki/Quick-Start) and examples**


###  PyOpticL v2.0 🚀 released! It is a complete rewrite of the PyOpticL library!
* [Migrate from 1.0 to 2.0](https://github.com/UMassIonTrappers/PyOpticL/tree/main#pyopticl-v1v2-migration) 
* [v2.0-Highlights](https://github.com/UMassIonTrappers/PyOpticL/wiki/v2.0-Highlights)
   * Including Improved Optics Simulation (Gaussian beam simulation)

<img width="400" src="https://github.com/user-attachments/assets/d80692a0-0d9f-4cb5-82f1-bce2f79c20ee" />


<!-- Trapped Ion quantum computer at UMass Amherst engineered with PyOpticL: -->
<!-- <img src="https://github.com/user-attachments/assets/1dbe2986-20e2-4f4e-9b4c-00dd31a4b656" width=50%> -->


### [Wiki](https://github.com/UMassIonTrappers/PyOpticL/wiki)
* [Installation Guide](https://github.com/UMassIonTrappers/PyOpticL#getting-setup)
* [Quick Start Guide](https://github.com/UMassIonTrappers/PyOpticL/wiki/Quick-Start)
* [Contributing to PyOpticL](https://github.com/UMassIonTrappers/PyOpticL/wiki/Contributing-to-PyOpticL)

### Modular baseplate examples:
* [Laser - Extended Cavity Diode Laser (with optical isolator)](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-‐-ECDL-with-Isolation-Baseplate)
* [Doublepass AOM Baseplate](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-‐-Doublepass-Baseplate)
* [Singlepass AOM Baseplate](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-‐-Singlepass-Baseplate)
* [Saturation Absorption Spectroscopy Baseplate](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-%E2%80%90-Saturation-Absorption-Spectroscopy-Baseplate)
* [Periscope](https://github.com/UMassIonTrappers/PyOpticL/wiki/Module-‐-Periscope)
* [CoverBox](https://github.com/UMassIonTrappers/PyOpticL/wiki/CoverBox)

<img width="300" src="https://github.com/user-attachments/assets/b3237dba-d979-49b2-821d-6eaf26edf847" />

### Modular Subsystems based on baseplates:
* [Laser Cooling and Detection](https://github.com/UMassIonTrappers/PyOpticL/wiki/Subsystem-‐-Laser-Cooling-and-Detection)
* [Raman Zeeman qubit](https://github.com/UMassIonTrappers/PyOpticL/wiki/Subsystem-%E2%80%90-Raman)
* [Photoionization](https://github.com/UMassIonTrappers/PyOpticL/wiki/Subsystem-%E2%80%90-Photoionization-Laser)
* [State Preparation and Measurement](https://github.com/UMassIonTrappers/PyOpticL/wiki/Subsystem-%E2%80%90-SPAM)

<img width="300" alt="image" src="https://github.com/user-attachments/assets/d0d951dc-ae7c-4db3-a713-b24ece516477" />

### Apparatus based on modular subsystems:
* [Trapped Ions - Strontium](https://github.com/UMassIonTrappers/PyOpticL/wiki/Apparatus-%E2%80%90-Trapped-Ions-%E2%80%90-Strontium)
* [Trapped Ions - Calcium](https://github.com/UMassIonTrappers/PyOpticL/wiki/Apparatus-%E2%80%90-Trapped-Ions-%E2%80%90-Calcium)
* [Project Redstone](https://github.com/UMassIonTrappers/PyOpticL/wiki/Apparatus-%E2%80%90-Quantum-Optics-%E2%80%90-Project-Redstone)

<img width="300" src="https://github.com/user-attachments/assets/1fd957f5-4196-419c-a6ce-1ff5015ce9ec" />

### Baseplate Examples and Designs
* [Designs](https://github.com/UMassIonTrappers/PyOpticL/tree/main/Designs)
* [3D Models and Technical Drawings](https://github.com/UMassIonTrappers/PyOpticL/tree/v1-legacy/Design/Module/3DModel)

### Pre-made Layouts

Macro files for pre-made layouts can be found in the PyOpticL directory. This can be found in: \
```<FreeCAD User Data Directory>/Mod/PyOpticL/Design``` \
On windows this is: \
```%APPDATA%\FreeCAD\Mod\PyOpticL\Design```

## PyOpticL v1/v2 Migration

The main branch of this project has been updated to PyOpticL v2.0! **This is a breaking change for existing designs.** Unless you manually update PyOpticL within FreeCAD, existing installs should be unaffected.

If you need to install v1:
* Use _Branch:_ v1-legacy when following the install instructions

To update to v2.0:
* Backup all locally changed files (optomech.py, stls, etc.)
* Uninstall PyOpticL from addon manager (This will delete all PyOpticL source files, **backup your changes**)
* Restart FreeCAD
* Re-install PyOpticL
___

## PyOpticL Community:

### Join the discussion on our Discord server: https://discord.gg/vV4NP6rXmp

### Experimental Labs using PyOpticL:
 * MIT QUANTA LAB - Prof. Isaac Chuang (Ba⁺ & Sr⁺)
 * MIT Quantum Photonics & AI Group - Prof. Dirk Englund (Rb)
 * [UC Berkeley - Prof. Aziza Suleymanzade (Rb)](https://github.com/hybrid-lab/PyOpticL_Rubidium_System)
 * [UW Madison - Prof. Josiah Sinclair (Rb)](https://github.com/hybrid-lab/PyOpticL_Rubidium_System/tree/sinclairlab-pyopticl)
 * UCONN - Prof. Simone Colombo (Rb, Sr)
 * Montana State University - Prof. Matt Jaffe (Rb)
 * National University of Singapore - Prof. Dzmitry Matsukevich (Yb⁺)
 * Stanford - Prof. Jonathan Simon (Rb)
 * Durham University Quantum Light and Matter - Tobias Franzen (Yb), Dani Pizzey (Rb)
 * Quera (Rb)
 * Harvard University (Rb)
 * Calvin Q (Rb)


<img width="800" src="https://github.com/user-attachments/assets/da1f5e60-a97e-493c-a372-581fa3e241eb" />


> We thank Ike and the MIT QUANTA LAB for sharing their C4PO ('CAD for Precision Optics') based on OpenSCAD which inspired this library.
