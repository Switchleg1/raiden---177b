"""Per-theme site character: the SPEC table."""
from __future__ import annotations

from ..plan.site_spec import SiteSpec

_DEFAULT = SiteSpec()


SPEC: dict[str, SiteSpec] = {
    "countryside": SiteSpec(
        ranges="foothills",
        ridge_shapes=("massif", "sawback", "domefield"), ridge_weight=0.9,
        # more than one mass: a single ridge somewhere on the map is why the
        # review said "no strong hills or slopes read" - the ground has to have
        # a high side and a low side across the whole strip
        ridge_count=(2, 3), water_kinds=("river",), road="main",
        build=("house", "barn"), field_kinds=("crop", "pasture", "orchard"),
        field_count=(5, 8), tree_props=("tree_clump", "pine_clump"),
        woods=(1, 3),
        places=("neighborhood", "woodland", "farmstead", "campground",
                "lake", "plains")),
    "farmland": SiteSpec(
        ridge_shapes=("domefield", "massif"), ridge_weight=0.7,
        ridge_count=(1, 1), water_kinds=("channel", "river"), road="main",
        build=("barn", "house"), field_kinds=("crop", "paddy", "pasture"),
        field_count=(8, 12), tree_props=("tree_clump", "pine_clump"),
        woods=(1, 2),
        places=("neighborhood", "woodland", "farmstead", "lake", "plains")),
    "forest": SiteSpec(
        ranges="alpine",
        ridge_shapes=("massif", "hogback"), ridge_weight=0.8,
        ridge_count=(1, 2),
        water_kinds=("river",), road="main", build=("house",),
        field_kinds=("pasture",), field_count=(1, 3),
        tree_props=("pine_clump", "tree_clump"), woods=(5, 8),
        treeline=True,
        places=("woodland", "campground", "lake", "farmstead")),
    "canyon": SiteSpec(
        ranges="badlands",
        ridge_shapes=("mesa", "hogback", "sawback"), ridge_weight=0.95,
        ridge_count=(2, 3), water_kinds=("wash",), road="main",
        build=(), field_count=(0, 0), tree_props=("dead_tree",),
        # no treeline: a contour-following row of bare trees along every ridge
        # flank shades into "tangled roots" and hides the canyon wall it was
        # supposed to trace
        woods=(1, 3), scree=True, treeline=False,
        places=()),
    "glacier": SiteSpec(
        ranges="alpine",
        ridge_shapes=("massif", "domefield", "cone"), ridge_weight=0.9,
        ridge_count=(2, 3), water_kinds=("channel",), road="main",
        build=("hut",), field_count=(0, 0),
        tree_props=("pine_snow",), woods=(2, 4), scree=True,
        places=("farmstead",)),
    "volcanic": SiteSpec(
        ranges="volcanic",
        ridge_shapes=("cone", "cone", "sawback", "hogback"), ridge_weight=0.95,
        ridge_count=(2, 3), ridge_prop="basalt_spire", water_kinds=(),
        road="main", build=(), field_count=(0, 0),
        tree_props=("dead_tree",), woods=(1, 3), scree=True,
        places=()),
    "wasteland": SiteSpec(
        ranges="badlands",
        ridge_shapes=("hogback", "massif"), ridge_count=(1, 2),
        water_kinds=("wash",), road="main", build=("crate_stack",),
        field_count=(0, 0), tree_props=("dead_tree",), woods=(2, 4),
        scree=True,
        places=()),
    "ruins": SiteSpec(
        ranges="foothills",
        ridge_shapes=("massif", "hogback"), ridge_weight=0.5,
        ridge_count=(1, 2), water_kinds=("river",), road="main",
        build=("house",), hamlet=True, field_kinds=("pasture",),
        field_count=(2, 4), tree_props=("tree_clump", "dead_tree"),
        woods=(1, 3),
        places=("neighborhood", "woodland", "farmstead", "lake")),
    "city": SiteSpec(
        ridge_shapes=("domefield",), ridge_count=(1, 1),
        ridge_weight=0.5, relief_gain=0.45, water_kinds=("river",),
        # no scree, no outcrops: boulders in a village read as three huge rocks
        # dropped onto a street, and nothing in a settlement is loose rock
        road="grid", scree=False,
        # the blocks build the city (see terrain.design.city): a frontage row or a
        # subdivision has nowhere to go in a grid, and only took a block's ground
        build=(), hamlet=False, meander=0.25,
        field_kinds=("lot", "park", "yard"), field_count=(10, 16),
        tree_props=("tree_clump",), woods=(0, 1), treeline=False,
        places=("highway",)),
    "airbase": SiteSpec(
        ridge_shapes=("domefield",), ridge_weight=0.3, ridge_count=(0, 1),
        water_kinds=("wash",), road="main", build=("warehouse_long",),
        field_count=(0, 0), tree_props=("tree_clump",), woods=(1, 2),
        places=("highway",)),
    "industrial": SiteSpec(
        ridge_shapes=("massif",), ridge_weight=0.35, ridge_count=(0, 1),
        water_kinds=("channel",), road="main",
        build=("warehouse_long", "storage_tank"), field_count=(0, 0),
        tree_props=("dead_tree",), woods=(1, 2),
        places=("highway",)),
    "swamp": SiteSpec(
        ridge_shapes=("ridge",), ridge_count=(1, 2), ridge_weight=0.4,
        relief_gain=0.35,
        water_kinds=("channel", "channel", "river"),
        # a swamp still gets ONE route - a causeway on the only dry ground
        # there is, crossing every channel - because without a road there is no
        # settlement either, and the sector reads as an empty green soup
        road="main", build=("hut_stilt",), hamlet=False, field_count=(0, 0),
        tree_props=("cypress_clump", "dead_tree"), woods=(3, 6),
        treeline=False,
        places=("farmstead",)),
    "ocean": SiteSpec(
        ridge_shapes=(), ridge_count=(0, 0), water_kinds=(), road="none",
        build=(), field_count=(0, 0), tree_props=(), woods=(0, 0),
        treeline=False, scree=False,
        places=()),

}
