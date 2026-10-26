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

The PyOpticL workbench includes **New Optical Schematic** and **Open Optical
Schematic** commands. Draw a planar optical system in a dedicated 2D workspace,
then use **Export Python…** to generate an ordinary PyOpticL macro. Export does
not execute the macro or modify an existing CAD layout.

- Drag symbols from the palette, or double-click a palette entry to place one.
  Click any free port, optionally click to add bends, then click another free
  port to connect. All ports have the same neutral color. Press **Esc** to cancel.
  Crossing paths stay separate.
- Passive optics have interchangeable **A/B** ports. Connect either side of a
  lens, mirror, waveplate, or iris; the editor infers propagation from the beam
  source, independently of the order in which connections were drawn. Arrows
  show that inferred direction. Ambiguous paths have no arrows and block export.
- Cube splitters have four neutral face ports. Transmission connects opposite
  faces; reflection pairs left/top and right/bottom for the drawn diagonal.
  Connect the incident face and both resulting branches; the remaining face
  stays unused in the current single-source model. Rotating a symbol rotates
  its port positions without changing these optical relationships.
- Move parts on the drawing grid, rotate with **R**, and use the grid/angle snap
  controls for 45° or 90° drawing. Double-click a connection to add an editable
  bend. Select a part, connection, or bend and press **Delete** to remove it.
- **Part bounds** toggles physical XY bounding circles, **off by default**.
  Each circle is centered on the part's optical/placement origin and conservatively
  encloses its modeled body, mounts, adapters, and attached hardware, including
  hidden hardware. Select an element to read the radius and diameter in mm.
  With nothing selected, change **Bounds scale (canvas units/mm)** to resize all
  circles together (default 4); **Refresh bounds** recalculates cached geometry.
  Visibility and scale are saved with the drawing and support undo/redo.
  Circle sizes share a scale, while schematic positions remain topological:
  overlapping circles do not constitute a physical collision check. Missing
  geometry is reported in the inspector without blocking editing or export.
- Select a beam connection, enable **Constrain beam length**, and enter its
  **Length (mm)** in the inspector. The constraint belongs to the beam between
  the two optical interaction points, independently of connection click order.
  Uncheck it to use the document's default beam length (or default open beam
  length for an open output), adjusted when needed to satisfy pinned positions.
  The beam inspector shows the resolved length. Splitter branches can have independent lengths.
- Select an optical element and enable **Constrain position** to pin its optical
  interaction point to absolute physical **X (mm)** and **Y (mm)** coordinates.
  Unchecking it restores automatic placement; an unconstrained source starts at
  the origin. Pins persist with the element through drawing edits, save/load,
  and undo/redo. The compiler adjusts unconstrained beam lengths, keeping them
  close to their defaults, to reach pinned positions along the current beam
  directions. Source direction and optic turns keep their existing values or
  port defaults; this does not solve for new angles. Incompatible pins, explicit
  lengths, or routing angles block export with a diagnostic on the element.
  Physical pins and lengths have no effect on the scale of the drawn schematic.
- Select a mirror or beamsplitter, enable **Constrain angle** in the element's
  inspector, and enter **Turn (deg)** or **Reflected turn (deg)**. Positive
  turns counterclockwise and negative clockwise in the physical XY plane;
  +90° is a right-angle bend, rather than a 90° incidence angle. Fractional
  angles are supported (absolute value at least 0.001° and less than 180°).
  The angle belongs to the optical element and stays with it when connections
  change. Uncheck the constraint to permit optimization; without an applied solution, the resolved port's default turn is used.
  Transmission stays straight, and single-ended fiber couplers
  have no direction change to constrain. This controls routing geometry;
  the current cube model does not simulate refraction through its outer faces.
- Select a part to edit its optical parameters, compatible part preset, and
  supported angle constraint. Existing angles from the earlier beam-based
  controls can also be edited or cleared here.
  Drawing positions and lengths have no
  physical scale. **Apply Drawing Directions** explicitly copies drawing
  tangents into physical routing hints while preserving explicit angle
  constraints; later drawing edits leave them alone.
  Default mirror/splitter turns follow the resolved incident port. Explicit
  physical turn overrides remain unchanged when connections are edited.
- Save editable drawings as `.pyopticl-schematic.json`. Undo/redo includes parts,
  connections, settings, and properties. Incomplete drawings can be saved.
  Version 1–4 drawings load through an in-memory migration that preserves existing
  port locations, bends, references, and physical settings. Files are written in
  version 5 format only when saved; opening a drawing does not rewrite it.
  Older drawings start with no path constraints, folding disabled, and Turning
  mirror roles. Older applied optimizations remain saved but are stale until
  rerun or cleared.
  Old component distances transfer to their incoming beams. An unfinished
  drawing retains unresolved old distances until source direction is known.
- **Validate** checks topology and physical origin overlaps. Every branch must
  end in a fiber output, beam stop, or explicit open output. Export is blocked
  until errors are resolved; click a message to locate the affected part.

Use **Path lengths…** to constrain the total geometric beam length between any
two connected components. Selecting two symbols prefills the endpoints. The
dialog lists target and current lengths, satisfaction status, and highlights the
unique route, including routes between splitter branches. Length is measured
between optical origins without refractive-index weighting. These constraints
also work with ordinary Python generation: free beam lengths adjust while
explicit lengths, positions, and the current routing angles remain fixed.
Conflicting or disconnected constraints block generation and optimization;
unfinished drawings remain saveable. References can be renamed without losing
constraints, and deleting an endpoint removes its constraints in the same edit.

Use **Optimize physical layout…** to fit the physical system into a rectangular
region in millimetres. Adjust X/Y, width/height, the assembly clearance (default
1 mm), and the constant beam keep-out diameter (default 1 mm). The live preview
shows full assembly disks and beam capsules independently of the schematic scale
and **Part bounds** display. Physical bounds must be available for every physical
part; **Refresh bounds** retries failed geometry resolution. The initial region
uses the current physical extents plus 10 mm, or the previous applied rectangle.

**Run** searches up to eight deterministic starts with force-directed motion and
constraint projection. Pins (including partial X/Y pins), explicit lengths and
signed turns remain hard constraints. Lenses, waveplates, irises, and splitter
transmission stay straight. Free mirror/reflected turns, lengths, and source pose
may change. The source inspector's **Constrain source direction** checkbox pins
its travel direction; existing explicit source angles remain constrained.
Beam crossings are allowed; unrelated assemblies must clear each beam capsule.
The packing model uses conservative full-assembly circles and a constant beam
width; it does not propagate Gaussian beam envelopes or perform a CAD collision
test.

Enable **Allow folding** on individual beams to let optimization add mirrors.
The beam's length constraint continues to mean **endpoint separation**, while a
path-length constraint controls the total routed length through inserted mirrors.
The inspector displays both measurements and the added mirrors' references and
physical positions. For example, an 80 mm endpoint separation and a 120 mm total
path can be satisfied by folding; an 80 mm separation and 80 mm path cannot have
a nonzero fold.

Each schematic mirror has a **Turning** (default) or **Folding** role. Turning
mirrors are always retained; their angle controls work as before. Folding mirrors
may be omitted unless protected by a position constraint, angle constraint,
incident explicit beam length, or use as a path-constraint endpoint. The inspector
explains protection. Omitted mirrors keep their drawing symbols and have no
current physical position. Adding a constraint makes the applied result stale
and protects that mirror on the next run.

The optimizer's added-mirror controls default to mounted 12.7 mm mirrors, at most
four per original beam and eight overall. Bare mirrors allow other diameters.
Their complete assembly bounds must resolve before Run. The bounded search
relaxes candidates in 200-iteration batches, prioritizes stressed permitted spans,
and tries offsets on both sides. It retains two candidates per active folding
count, including infeasible intermediate layouts. All candidates share each
start's 5,000-iteration budget and 20 projection passes per iteration. A folding
mirror becomes eligible for removal above the configured **interior arm angle**
(default 110°; 180° is straight), with 10° insertion/removal hysteresis and a
200-iteration cooldown. Removal preserves every hard constraint. Feasible results
are ranked by fewest active Folding mirrors, then normalized spring energy.

**Apply** is enabled only after reconstructing exact optical geometry and checking
all constraints and clearances to 1e-6 mm / 1e-6 degrees. It is one undoable edit,
preserves the topological drawing, and stores free values separately from hard
constraints. The inspectors show these effective values with their constraint
checkboxes still unchecked. Export uses the applied source pose, lengths, turns,
and part orientations and retains the generated script's runtime trace check.
Generated mirrors and bypassed schematic mirrors belong to the applied physical
graph: the preview and export identify additions and omissions, while the
schematic drawing and explicit constraints remain unchanged. Export uses the
actual final open-beam segment lengths.
**Cancel** closes without changing the schematic. **Clear optimized layout**
restores deterministic generation without removing constraints.

Part, topology, constraint, folding permission, mirror role, default-length,
packing, search, or geometry-setting changes
make an applied solution stale and block export until it is rerun or cleared.
Stale results survive save/load and undo/redo. Drawing edits, reference renames,
and display settings preserve a solution. If the search budget expires, the dialog
reports **No feasible layout found** and its largest remaining violations; this is
not a proof that the requested packing is impossible.

Reproducible optimizer examples include a [pinned Turning mirror](Designs/schematics/optimization/pinned-mirror.png),
a [folded splitter system](Designs/schematics/optimization/splitter-fold.png),
[two automatically added mirrors](Designs/schematics/optimization/adaptive-multiple-folds.png),
[removal of a Folding mirror](Designs/schematics/optimization/adaptive-remove-fold.png),
and a [constrained +90° splitter with an added branch mirror](Designs/schematics/optimization/adaptive-splitter-90.png).
Each comparison shows the unchanged topological drawing and physical layouts
before and after packing. Editable `*-before.pyopticl-schematic.json` and
`*-after.pyopticl-schematic.json` files, generated Python, and
[verification results](Designs/schematics/optimization/verification.json) are in
the same folder. Before files retain the target rectangle, ready for **Run**.
The pinned-mirror draft intentionally fails its output position constraints;
its after file satisfies them. The splitter example explicitly constrains BS1's
reflected turn to +90°; both branch directions are checked from optimized and
exported coordinates. The adaptive examples also independently measure their
total paths from exported coordinates and check constrained endpoint separations.
These examples use analytical bounds of the bare primitive models. The separate
[native FreeCAD report](Designs/schematics/optimization/native-verification.json)
records 25 passing integration tests, including real assembly bounds and CAD
traces of all five saved examples. Those checks measure actual segment lengths
and interaction coordinates, including the two added mirrors and constrained
splitter branch. Reproduce the solver and actual Qt Run/Apply/undo/redo checks
with `QT_QPA_PLATFORM=offscreen python Designs/schematics/optimization/generate.py --render`.
Inside a FreeCAD-capable environment, add `--cad` to resolve actual geometry and
execute each exported layout's runtime trace check.

Open [the branched example](Designs/schematics/branched.pyopticl-schematic.json)
to try a mirror, lens, beamsplitter, fiber output, and beam stop. Its
[exported Python](Designs/schematics/branched.py) demonstrates the generated code.
Run exported `.py` files using the same FreeCAD macro workflow as existing
designs. The script builds a `Layout`, places parts, computes a `BeamPath`, and
checks the resulting optical connections. Refine its `PLACEMENTS` (mm/degrees),
`PARAMETERS`, and `SOURCE` dictionaries as needed. Changes to those dictionaries
are explicit: moving the source does not automatically relocate the other parts.
Regeneration replaces exported Python; Python edits do not update the schematic.

The first version supports one source and acyclic chains/splitter branches in a
single optical plane, with curated half-inch mounted optics and bare alternatives.
Mounted presets require a 12.7 mm optic. Bare spherical lenses support positive
or negative focal lengths. Splitter ratios must be strictly between zero and one.
Double passes, beam merging, multiple sources, PBS/AOM routing, module links,
nonrectangular packing regions, and fabrication constraints are not yet supported.
Default spacing produces a draft; a trace mismatch identifies connections whose
physical placements need adjustment. A separate FreeCAD document is convenient
for trying generated drafts alongside existing designs.

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
Source/fiber-source symbols remain emitters; receiver, stop, and open-output
symbols remain terminals. Neutral optic ports do not add double-pass or
counterpropagating-beam support to the current compiler.

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
