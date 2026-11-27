"""The data passed between the stages: an Item being built up, and the problems found on the way."""

from dataclasses import dataclass, field

from .util import GLOBAL_BBOX, GLOBAL_GEOM


@dataclass
class ItemDraft:
    """One dataset on its way to becoming a STAC Item. Plain dicts for props and assets, so rules can edit them."""
    id: str
    branch: str            # e.g. "simulations", "derived/MCS-tracks"
    coll: str              # Collection id, e.g. "UM"
    coll_title: str
    props: dict            # STAC properties, including "datetime" / "start_datetime" / "end_datetime" as strings
    assets: dict           # asset key -> asset dict (href, type, roles, title, extension fields)
    meta: dict             # the source's own metadata (HK25 Intake), for rules that need it
    bbox: list = field(default_factory=lambda: list(GLOBAL_BBOX))
    geometry: dict = field(default_factory=lambda: dict(GLOBAL_GEOM))
    links: list = field(default_factory=list)  # extra links: {"rel", "href", "title"?, "type"?}

    @property
    def frequencies(self):
        return sorted({k.split(".")[0] for k in self.assets})

    @property
    def zooms(self):
        return sorted({a["km_scale:zoom"] for a in self.assets.values() if "km_scale:zoom" in a})

    @property
    def data_variables(self):
        return sorted({v for a in self.assets.values() for v, d in a.get("cube:variables", {}).items()
                       if d.get("type") == "data"})

    @property
    def is_global_footprint(self):
        return self.bbox == GLOBAL_BBOX


class Problems:
    """What the build found wrong or worth knowing, per dataset, in the order found. Written to problems.txt."""

    def __init__(self):
        self._items = []  # (dataset id, message)

    def add(self, dsid, message):
        self._items.append((dsid, message))

    def replace(self, dsid, old, new):
        """Replace a message recorded earlier (e.g. a placeholder that a later stage resolved)."""
        i = self._items.index((dsid, old))
        self._items[i] = (dsid, new)

    def lines(self):
        return [f"{d}: {m}" for d, m in self._items]

    def __len__(self):
        return len(self._items)
