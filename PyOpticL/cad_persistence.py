"""Pickle component state with explicit, importable FreeCAD datum reducers.

These are value datums, not document objects or B-rep geometry. Keep the dispatch
local to our pickler; do not alter serialization of other FreeCAD workbenches.
"""
import copyreg
import io
import pickle
import FreeCAD as App


def _vector(x,y,z):
    return App.Vector(x,y,z)


def _rotation(quaternion):
    return App.Rotation(*quaternion)


def _placement(position,quaternion):
    return App.Placement(App.Vector(*position),App.Rotation(*quaternion))


def _reduce_vector(value):
    return _vector,tuple(value)


def _reduce_rotation(value):
    return _rotation,(tuple(value.Q),)


def _reduce_placement(value):
    return _placement,(tuple(value.Base),tuple(value.Rotation.Q))


def dumps(state):
    stream=io.BytesIO()
    writer=pickle.Pickler(stream)
    writer.dispatch_table=copyreg.dispatch_table.copy()
    writer.dispatch_table.update({type(App.Vector()):_reduce_vector,
                                  type(App.Rotation()):_reduce_rotation,
                                  type(App.Placement()):_reduce_placement})
    writer.dump(state)
    return stream.getvalue().hex()


def loads(state):
    return pickle.loads(bytes.fromhex(state))
