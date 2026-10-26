# First connection example

- [F260FC-1550](https://www.thorlabs.com/item/F260FC-1550): FC/PC collimator, external M11 x 0.5 body thread.
- [AD1109F](https://www.thorlabs.com/item/AD1109F): internal M11 x 0.5 end for this collimator; external SM05 mount end. The additional M9 thread is not the selected connection.
- [KA05TA](https://www.thorlabs.com/item/KA05TA): SM05 (0.535-40) internal through-thread, two SM05KRR rings supplied. Determine which ring must be removed for adapter insertion using the nominal CAD. Keep unused supplied hardware in the BOM with an uninstalled disposition.
- [Collimator adapter table](https://www.thorlabs.com/fixed-focus-collimation-packages-fcpc-connectors?tabName=Overview) establishes the intended adapter family.

This chain passes the documented mating-standard check. Full seating, thread engagement, access and the SPDC support still require the catalog's geometric verification results. Reject M11 x 0.75, M9 x 0.5, SM1, or a second external SM05 as direct substitutes. An FC/APC fiber connector is not an FC/PC mating connector. Optical suitability at 1550 nm must be checked separately from the mechanical chain.

For this project, the user selected the M11 thread end as the nominal assembly datum. The pinned F260FC-1550 CAD measures 2.9972 mm from front to thread end. Align that plane to the AD1109F opening; do not use the full 6.35 mm internal depth as insertion travel. This convention is not a universal bottoming or torque specification.
