"""Native interface endpoint tolerance when retracing a terminated beam."""
from types import SimpleNamespace
import unittest

import numpy as np

from PyOpticL.beam_path import Interface


class InterfaceEndpointTests(unittest.TestCase):
    def test_retrace_accepts_roundoff_at_endpoint_but_rejects_beyond_it(self):
        interface = SimpleNamespace(
            get_global_position=lambda: np.array((150.0, 0.0, 0.0)),
            get_global_normal=lambda: np.array((-1.0, 0.0, 0.0)),
            single_sided=True,
            max_angle=90,
            shape="circular",
            diameter=5,
        )
        beam = SimpleNamespace(
            get_global_position=lambda: np.zeros(3),
            get_global_direction=lambda: np.array((1.0, 0.0, 0.0)),
            get_object=lambda: SimpleNamespace(EndObject=object()),
            distance=150.0 - 1e-12,
        )
        np.testing.assert_allclose(
            Interface.get_intercept(interface, beam), (150, 0, 0)
        )
        beam.distance = 150.0 - 1e-4
        self.assertIsNone(Interface.get_intercept(interface, beam))


if __name__ == "__main__":
    unittest.main()
