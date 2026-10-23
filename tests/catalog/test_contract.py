import json
import unittest
from dataclasses import replace
from PyOpticL.component_contract import *

class ContractTests(unittest.TestCase):
    def test_round_trip_and_axes(self):
        c = ComponentContract('test', '1', 'lab', '', 'assembly',
            frames=(Frame('optic', rotation=(0, 0, 90)),),
            dofs=(DOF('tip', 'rotation', 'optic', (1, 0, 0), 'mirror', 'drawing'),))
        restored = ComponentContract.from_dict(json.loads(json.dumps(c.to_dict())))
        self.assertEqual(c, restored)
        self.assertAlmostEqual(c.axes()['tip'][1], 1)
        self.assertAlmostEqual(c.axes((0, 0, 90))['tip'][0], -1)
        self.assertIsNone(c.dofs[0].limits)
        self.assertEqual(replace(c, dofs=()).summary(), 'Fixed after installation')

    def test_invalid_contract(self):
        with self.assertRaises(ValueError):
            DOF('x', 'translation', 'origin', (0,0,0), 'part', 'drawing')
        with self.assertRaises(ValueError):
            ComponentContract('x', '1', '', '', 'generic', optical_reference='missing')
        with self.assertRaises(ValueError):
            DOF('x', 'rotation', 'origin', (1,0,0), 'part', 'drawing', (1,-1))

    def test_connections(self):
        def threaded(d,p,g):
            return MechanicalInterface('a','origin','thread',Thread('explicit',g,d,p))
        m11=threaded(11,.5,'external')
        self.assertTrue(connection_check(m11,threaded(11,.5,'internal'))[0])
        for wrong in [threaded(11,.75,'internal'),threaded(9,.5,'internal'),threaded(11,.5,'external')]:
            self.assertFalse(connection_check(m11,wrong)[0])
        pc=MechanicalInterface('f','origin','fiber',connector='FC/PC')
        apc=MechanicalInterface('f','origin','fiber',connector='FC/APC')
        self.assertFalse(connection_check(pc,apc)[0])
        self.assertFalse(connection_check(pc,MechanicalInterface('f','origin','fiber'))[0])

if __name__=='__main__': unittest.main()
