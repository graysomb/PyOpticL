import unittest
from PyOpticL.component_contract import Frame
from PyOpticL.stage_contract import LinearStageSpec


class StageContractTests(unittest.TestCase):
    def test_reference_and_normalized_axis(self):
        s=LinearStageSpec(Frame('base'),Frame('payload',(1,2,23)),(2,0,0),(-3,7),1)
        self.assertEqual(s.axis,(1,0,0))
        self.assertEqual(s.payload_at(1).position,(1,2,23))
        self.assertEqual(s.payload_at(7).position,(7,2,23))
        self.assertEqual(s.payload_at(-3).position,(-3,2,23))

    def test_arbitrary_axis_and_limits(self):
        s=LinearStageSpec(Frame('base'),Frame('payload'),(0,3,4),(-5,5))
        self.assertEqual(s.payload_at(5).position,(0,3,4))
        for value in (6,-6,float('nan'),float('inf')):
            with self.assertRaises(ValueError):s.payload_at(value)

    def test_invalid_configuration(self):
        for axis,limits,ref in (((0,0,0),(-1,1),0),((1,0,0),(1,1),1),
                               ((1,0,0),(-1,1),2),((float('nan'),0,0),(-1,1),0)):
            with self.assertRaises(ValueError):LinearStageSpec(Frame('base'),Frame('payload'),axis,limits,ref)
