from showcat.adapters.sources.custom.aladdin import AladdinAdapter
from showcat.adapters.sources.custom.bluediamond import BlueDiamondAdapter
from showcat.adapters.sources.custom.kentonclub import KentonClubAdapter
from showcat.adapters.sources.custom.laurelthirst import LaurelThirstAdapter
from showcat.adapters.sources.custom.mcmenamins import CrystalBallroomAdapter
from showcat.adapters.sources.custom.nofun import NoFunBarAdapter
from showcat.adapters.sources.custom.rhp import HawthorneAdapter, RoselandAdapter
from showcat.adapters.sources.custom.spareroom import SpareRoomAdapter
from showcat.adapters.sources.custom.starday import StardayTavernAdapter
from showcat.adapters.sources.custom.truewest import TrueWestAdapter

ALL_CUSTOM_ADAPTERS = [
    # Venue-direct Etix scrapers (Phase 8 — de-Ticketmaster)
    AladdinAdapter,
    RoselandAdapter,
    HawthorneAdapter,
    TrueWestAdapter,
    CrystalBallroomAdapter,
    # Small / door venues
    BlueDiamondAdapter,
    LaurelThirstAdapter,
    NoFunBarAdapter,
    StardayTavernAdapter,
    KentonClubAdapter,
    SpareRoomAdapter,
]
