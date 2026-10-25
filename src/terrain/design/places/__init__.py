"""Places: the blueprints a sector is built from.

No re-exports: import from the module that defines a name. The plan's
model, the geometry it measures with and the planner import one another's
modules, and a package that re-exported eagerly would put a cycle in that.
"""
