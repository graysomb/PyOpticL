---
name: thorlabs-connect-parts
description: Find documented Thorlabs adapter chains between optical components and mounts, checking thread standards, connector types, seating, engagement, clear aperture and assembly access separately from optical suitability.
---

# Connect Thorlabs parts

Identify exact endpoint part numbers and the intended optical direction. Consult official product compatibility tables, drawings and STEP files. Follow a documented chain; never treat nominal diameter alone as proof of fit.

For each connection record:

1. Exact standard, pitch and gender on each side (SM05 is 0.535-40, not M13.5; M11 x 0.5 is not SM05).
2. Mating orientation, seating faces, available engagement and whether a retaining ring must be removed or repositioned.
3. Through bore versus optical beam envelope, shoulder clearance, nearby solids and tool/assembly access.
4. Source URL and drawing revision; distinguish directly documented facts from CAD-derived offsets and assumptions.

Use `PyOpticL.lab_catalog.connection_interfaces()` and `component_contract.connection_check()` for an initial standard check. A pass checks only thread or connector compatibility, not seating or complete assembly feasibility. Same-gender threads, pitch/diameter mismatches, FC/APC versus FC/PC, or unknown interfaces must not be accepted. Unsupported or ambiguous links remain unverified.

Read [the first chain](references/f260fc-chain.md) for F260FC-1550 → AD1109F → KA05TA. Do not replace AD1109F with a similarly named adapter.

Report mechanical compatibility separately from optical suitability: wavelength/coating, fiber type, connector polish, collimation, aperture, polarization and power suitability require their own evidence. A mechanical fit does not establish coupling efficiency. Keep DOFs descriptive; the mount has tip, tilt and axial translation, not independent lateral XY translation. Do not add motion controls or motor commands.

Deliver a compact connection table, a source-backed proposed chain, and any unresolved checks. Do not label SPDC support compatibility verified until its mounting holes, seats and access have been compared with this exact assembled chain.
