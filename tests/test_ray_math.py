"""Numerically stable chief-ray refraction, including nearly centered hits."""

import unittest

from PyOpticL.ray_math import add, lens_direction, mul, norm, sub, unit, yaw


class LensDirectionTests(unittest.TestCase):
    def assert_direction(self, actual, expected):
        self.assertLess(norm(sub(actual, expected)), 1e-14)
        self.assertAlmostEqual(norm(actual), 1, delta=1e-14)

    def test_nearly_centered_hit_does_not_amplify_plane_roundoff(self):
        normal = yaw((1, 0, 0), 1.677153261674128)
        transverse = yaw((0, 1, 0), 1.677153261674128)
        incoming = (0.999571611613627, 0.02926761445927556, 0)
        # Subtracting two world-space points leaves a tiny normal component.
        radial = (1.8194583617514581e-09, -6.213973335889023e-08, 0)
        clean = mul(transverse, sum(a * b for a, b in zip(radial, transverse)))
        incidence = sum(a * b for a, b in zip(incoming, normal))
        expected = unit(sub(incoming, mul(clean, abs(incidence) / 50)))
        self.assert_direction(lens_direction(incoming, normal, radial, 50), expected)

    def test_thin_lens_slopes_in_both_directions_and_focal_length_signs(self):
        for angle in (-135, 0, 37, 179):
            for sign in (-1, 1):
                for focal_length in (-50, 50):
                    with self.subTest(angle=angle, sign=sign, focal_length=focal_length):
                        normal = yaw((1, 0, 0), angle)
                        incoming = yaw(unit((sign, 0.2, -0.1)), angle)
                        offset = yaw((0, 2, -3), angle)
                        expected = yaw(unit((sign, 0.2 - 2 / focal_length,
                                                  -0.1 + 3 / focal_length)), angle)
                        self.assert_direction(
                            lens_direction(incoming, normal, offset, focal_length), expected
                        )

    def test_continuous_at_center_with_normal_roundoff_and_tiny_offsets(self):
        normal = unit((1, 2, 3))
        transverse = unit((2, -1, 0))
        incoming = unit(add(normal, mul(transverse, 0.1)))
        incidence = sum(a * b for a, b in zip(incoming, normal))
        for radius in (0, 1e-14, 1e-10, 1e-7, 0.01):
            for noise in (-1e-14, 0, 1e-14):
                with self.subTest(radius=radius, noise=noise):
                    radial = add(mul(transverse, radius), mul(normal, noise))
                    expected = unit(sub(incoming, mul(transverse, radius * incidence / 50)))
                    self.assert_direction(lens_direction(incoming, normal, radial, 50), expected)

    def test_parallel_ray_preserves_direction(self):
        self.assertEqual(lens_direction((0, 1, 0), (1, 0, 0), (0, 2, 0), 50), (0, 1, 0))


if __name__ == "__main__":
    unittest.main()
