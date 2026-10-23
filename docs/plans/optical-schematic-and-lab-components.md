# Optical schematic and lab component implementation plan

Status: proposed implementation, 2026-10-23.

Extend PyOpticL with the components and mechanical conventions used in the lab,
then provide a 2D schematic editor that generates FreeCAD optical assemblies
without requiring users to write Python. The first complete milestone is a
schematic-driven HOM interferometer with an adjustable delay module.

## Architecture

Keep PyOpticL as the optical-layout and CAD-generation foundation. Add a separate
lab catalog and a shared system model consumed by the schematic editor, physical
layout editor, validators, and CAD generator. Retain existing script workflows.

The shared model should contain:

- Stable component and port IDs, component definitions, and catalog revisions.
- Named optical ports and directed beam connections, including multiple inputs,
  shared optics, counterpropagation, and closed paths.
- Wavelength, polarization, beam parameters, and beam or mode identity.
- Hardware selections, assembly hierarchy, placements, and coordinate frames.
- Physical adjustment DOFs, layout variables, constraints, and module boundaries.
- Separate schematic coordinates and physical coordinates with explicit units.

Use a versioned JSON representation with schema validation and migrations. Keep
the model independent of FreeCAD where practical so connectivity and constraint
tests can run without the GUI. Python export is optional; normal save/load and
editing must not require code.

Use PyOpticL for nominal propagation and CAD generation. Integrate OpticsWorkbench
as an optional geometric ray-tracing check through an adapter that shares object
identities and placements. Quantum interference, SPDC generation, and laser
mode-locking dynamics require separately validated analysis models.

## Existing foundations to preserve

- `PyOpticL/library/optics.py`: generic optics and mount composition.
- `PyOpticL/library/thorlabs.py`: existing vendor hardware, including K05S1 and RSP05.
- `PyOpticL/layout.py`: component hierarchy, placement, and drilling geometry.
- `PyOpticL/beam_path.py`: branching, Gaussian propagation, Jones polarization,
  and placement along beams.
- `PyOpticL/library/adapters.py`: existing adapter families.
- `guiCommands.py` and `PyOpticL/drawings.py`: model conversion, parts export,
  and drawing generation.
- `Designs/modules/half_inch_library.py`: an example of reusable component presets.

The current STEP importer in `PyOpticL/utils.py` converts shapes into meshes.
Retain solid geometry alongside display meshes where precise mechanical checks
or OpticsWorkbench tracing require surfaces.

## Component and mechanical changes

| Priority | Change | Required behavior |
| --- | --- | --- |
| First | Lab component catalog | Separate generic optical symbols from vendor parts and custom mechanical implementations; support verified catalog presets. |
| First | Optical and mechanical reference frames | Define incidence points, optical axes, mounting faces, seating surfaces, hole patterns, and adjustment pivots separately. Changing mount or optic thickness preserves the intended nominal optical geometry. |
| First | Physical DOFs | Store axes, pivots, limits, nominal settings, and fixed/moving bodies; move grouped optics together. |
| First | Baseplate conventions | Support beam axes aligned with the table grid, preferred heights, spacers, stepped plates, and module interfaces. Make rules configurable, with explicit exceptions. |
| First | Custom holder families | Parameterize proven PBS clamps, beam-displacer clips, ELL16 housings, coupling blocks, and alignment irises. |
| Next | Beam displacers and selective optics | Add horizontal/vertical displacement, perforated waveplates, polarizing plates, and custom apertures. Allow different paths to experience different regions of one optic. |
| Next | Optical connection graph | Represent splitting, recombination, shared optics, and loops explicitly; add closure constraints and bounded traversal of cyclic paths. |
| Next | Clearance checks | Detect beam clipping, mount collisions, conflicting holes, insufficient stage travel, inaccessible adjusters, and assembly-access problems. |
| Next | Optical diagnostics | Extend existing propagation with path differences, mode matching, and coupling estimates; distinguish geometric length, optical phase length, and group delay. |
| Later | Oscillator components and analysis | Add curved/chirped mirrors, output couplers, SESAM, gain glass, piezos, and cavity round-trip analysis. |

Catalog entries should include supported optic dimensions, clear apertures,
front/rear loading behavior, mounting interfaces, material, threads, tolerances,
part numbers, revision, and source drawings. Track purchased and fabricated parts
separately in the BOM. Import existing STEP geometry as reference components;
rebuild selected custom holders parametrically. Obtain neutral CAD exports for
Inventor-only assets before depending on them in the generation pipeline.

Generate custom parts from validated families. Automatic invention of arbitrary
mounting hardware is outside the initial scope.

## Degrees of freedom

Physical adjustment and design-time freedom are different properties. The layout
solver must only vary explicitly permitted design variables; it must not satisfy
alignment by moving a body that is physically fixed.

| Assembly | Physical adjustment |
| --- | --- |
| Kinematic mirror | Two angular adjustments about defined pivots |
| Waveplate | Rotation about the optical axis |
| Perforated waveplate holder | Rotation plus transverse translation |
| Fiber coupling assembly | Only the translations and rotations supplied by the selected hardware |
| Delay module | Translation of the entire moving mirror assembly |
| Piezo-mounted cavity optic | Limited displacement along a specified axis |

Each DOF needs a local reference frame, axis, pivot where applicable, range,
nominal value, and fixed/moving-body relationship. Distinguish coarse placement,
alignment adjustment, and operational scanning. Unknown travel or pivot data
must remain explicitly unverified until checked against drawings or hardware.

## Schematic workflow

1. Place simple symbols for sources, mirrors, lenses, PBSs, waveplates, beam
   displacers, couplers, crystals, apertures, and detectors.
2. Connect named ports with beams and specify wavelength, polarization, and
   relevant beam parameters.
3. Attach DOF annotations to optics or groups of optics.
4. Add constraints such as equal arm lengths, shared beam height, or a target
   waist at a crystal.
5. Select hardware or apply lab presets.
6. Switch to a linked dimensioned layout view to place the system on the table
   grid, lock coordinates, set distances, and define module boundaries.
7. Validate the layout and generate the FreeCAD assembly, plates, drawings,
   and BOM.

Schematic bends do not create physical beam turns: a physical turn requires an
optic. Crossing lines do not imply coupling. Schematic spacing does not define
physical path length unless explicitly linked. Show missing constraints,
conflicting constraints, and remaining layout freedoms before generation.

Use height labels and out-of-plane symbols in the 2D view, with an elevation view
when needed for vertical beam displacement. Keep 3D geometry in the shared model.

A FreeCAD-integrated Qt graphics canvas is the initial UI candidate. Confirm the
Qt/PySide version bundled with the supported FreeCAD installation before choosing
APIs. Qt's [Diagram Scene example](https://doc.qt.io/qtforpython-6/examples/example_widgets_graphicsview_diagramscene.html)
illustrates symbol and connection editing. Include selection, property editing,
undo/redo, and save/load from the first usable prototype.

The shared model is the source of truth. Regeneration should update generated
objects by stable ID. Define an explicit policy for manual CAD changes so that
regeneration cannot silently discard them.

## Implementation milestones

### 1 Establish the component contract and initial catalog

- [ ] Define coordinate, unit, port, DOF, and mounting-interface conventions.
- [ ] Implement one mirror/mount combination, one coupler, one PBS holder, one
  rotation assembly, and one translation stage.
- [ ] Record optical-to-mechanical offsets and provenance from reference CAD.
- [ ] Preserve existing scripted component creation through adapters or defaults.

Acceptance: known incidence points and mounting holes match reference geometry
within explicitly chosen engineering tolerances. Swapping compatible mounts or
mirror thicknesses preserves nominal incidence points and updates mounting holes.

### 2 Build a minimal schematic to CAD workflow

- [ ] Implement the versioned shared model and save/load.
- [ ] Add symbol placement, named connections, property editing, DOF annotations,
  and a dimensioned layout view.
- [ ] Generate a coupler–mirror–lens–coupler assembly through PyOpticL.
- [ ] Add connectivity and constraint diagnostics.

Acceptance: create, save, reopen, edit, and regenerate the example without Python.
Repeated generation does not duplicate components. Invalid connections and
incompatible hardware produce actionable messages.

### 3 Reproduce the HOM assembly and delay module

- [ ] Add multiple inputs, shared optics, grid/height rules, and path constraints.
- [ ] Implement the relevant mirror mounts, PBS holder, ELL16 holder, and delay
  rail/stage/mirror-plate assembly.
- [ ] Add mechanical clearance and motion-envelope checks.
- [ ] Generate baseplates and manufacturing outputs from the solved layout.

Acceptance: match reference incidence points, hole patterns, and height stacks.
Stage motion moves both mirrors rigidly and changes the traced path correctly.
For a validated ideal double-pass geometry, check path change against twice the
stage displacement. Verify clearances throughout the specified travel range.

This is the first complete project milestone.

### 4 Add SPDC and displacement components

- [ ] Add horizontal/vertical beam displacers, perforated waveplates, polarizing
  plates, custom clips, and crystal holders.
- [ ] Support multiple wavelengths and multiple paths through shared components.
- [ ] Add beam-envelope clipping and Gaussian mode-matching diagnostics.
- [ ] Reproduce the SPDC and displacement layouts as regression examples.

Acceptance: distinguish passage through a waveplate hole from passage through
the birefringent material; preserve beam identity through displacement and
recombination. Compare simple propagation cases against independent analytic
calculations before using diagnostics to evaluate complete assemblies.

### 5 Extend to the oscillator and nonlinear assemblies

- [ ] Add curved-mirror propagation and cavity closure/round-trip analysis.
- [ ] Add output-coupler, SESAM, gain-medium, piezo, and thermal-mount definitions.
- [ ] Add interchangeable bulk-crystal and waveguide SHG assemblies, prioritizing
  the bulk-crystal configuration described in the later project notes.
- [ ] Define separate interfaces for advanced nonlinear, laser, and quantum models.

Acceptance: validate passive cavity geometry and Gaussian eigenmode calculations
against simple reference cavities. Clearly distinguish nominal CAD components
and approximate optical models from validated nonlinear or quantum simulations.

## Reference projects

The source assets currently live in the sibling `Data` directory of the MountGen
workspace, outside this Git repository. Paths below are workspace-relative;
the assets are not included in this plan's commit.

| Source | Requirements carried into this plan |
| --- | --- |
| `Data/HOM Mount/Documentation.pdf` | Incidence-point anchoring, front/rear loading offsets, alternative mirror hole patterns, PBS clamp, ELL16 holder |
| `Data/HOM Mount/DelayModules.pdf` | XR25 rail/stage assembly, shared moving mirror plate, stepped height stack, standalone module |
| `Data/SPDC Mach Zhender V2/(9+) Modular Source Development _ Notion.pdf` | Table-grid alignment, preferred heights/spacers, coupling and clipping diagnostics |
| `Data/SPDC Mach Zhender V2/Assembly 1.step` | Existing custom clips, output mounts, spacer, and wavelength-specific paths |
| `Data/Displacement setup/austin_honors_thesis (1).pdf` | Beam displacers, perforated waveplates, ELL16 plus transverse translation, assembly access and clipping |
| `Data/Displacement setup/displacement_optics.png` | Initial schematic symbol vocabulary |
| `Data/1550 MLL/BOM_ErYbGlass-laser_100MHz.xlsx` | Oscillator optics, stages, piezos, custom copper parts, and existing catalog overlap |
| `Data/1550 MLL/ErYbLaserParts/` | Mechanical reference assets, including Inventor parts and assemblies |
| `Data/SHG mount/(9+) 100 MHZ pump laser source _ Notion.pdf` | Bulk-crystal and waveguide variants; later notes return to bulk crystal because of spatial-mode concerns |

## Decisions to resolve during implementation

- Supported FreeCAD version and compatible Qt/PySide APIs.
- Which lab hardware variants have verified reference frames and adjustment data.
- Physical-layout constraint solver and handling of under/overconstrained systems.
- Engineering tolerances and machining rules for each fabricated component family.
- Scope of optical phase, group delay, and coherent recombination calculations.
- Storage and distribution of reference CAD assets and catalog revisions.

Resolve these through the milestone prototypes and reference assemblies. They do
not prevent starting the initial component contract and catalog.
