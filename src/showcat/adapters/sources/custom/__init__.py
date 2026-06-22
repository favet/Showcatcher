from showcat.adapters.sources.custom.aladdin import AladdinAdapter
from showcat.adapters.sources.custom.bluediamond import BlueDiamondAdapter
from showcat.adapters.sources.custom.kentonclub import KentonClubAdapter
from showcat.adapters.sources.custom.laurelthirst import LaurelThirstAdapter
from showcat.adapters.sources.custom.mcmenamins import CrystalBallroomAdapter
from showcat.adapters.sources.custom.mcmenamins_main import (
    AlsDenAdapter,
    EdgefieldAdapter,
    LolasRoomAdapter,
    WhiteEagleAdapter,
)
from showcat.adapters.sources.custom.nofun import NoFunBarAdapter
from showcat.adapters.sources.custom.novapdx import NovaPdxAdapter
from showcat.adapters.sources.custom.revhall import RevolutionHallAdapter
from showcat.adapters.sources.custom.getdown import GetDownAdapter
from showcat.adapters.sources.custom.rhp import (
    AlbertaRoseAdapter,
    HawthorneAdapter,
    HoloceneAdapter,
    RoselandAdapter,
    WonderBallroomAdapter,
)
from showcat.adapters.sources.custom.showdown import ShowdownAdapter
from showcat.adapters.sources.custom.spareroom import SpareRoomAdapter
from showcat.adapters.sources.custom.starday import StardayTavernAdapter
from showcat.adapters.sources.custom.truewest import TrueWestAdapter

ALL_CUSTOM_ADAPTERS = [
    # Venue-direct Etix scrapers (Phase 8 — de-Ticketmaster)
    AladdinAdapter,
    RoselandAdapter,
    HawthorneAdapter,
    WonderBallroomAdapter,
    TrueWestAdapter,
    CrystalBallroomAdapter,
    RevolutionHallAdapter,
    WhiteEagleAdapter,
    AlsDenAdapter,
    LolasRoomAdapter,
    EdgefieldAdapter,
    # Phase 9 venue expansion
    AlbertaRoseAdapter,
    HoloceneAdapter,
    GetDownAdapter,
    ShowdownAdapter,
    NovaPdxAdapter,
    # Small / door venues
    BlueDiamondAdapter,
    LaurelThirstAdapter,
    NoFunBarAdapter,
    StardayTavernAdapter,
    KentonClubAdapter,
    SpareRoomAdapter,
]
