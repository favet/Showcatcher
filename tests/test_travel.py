"""Tests for showcat.core.travel — venue travel-time lookup and distance signal."""
from showcat.core.travel import (
    _FALLBACK_TRAVEL_MINUTES,
    distance_signal,
    lookup_travel,
    normalize_venue_name,
)


class TestNormalizeVenueName:
    def test_removes_theater(self) -> None:
        assert normalize_venue_name("Aladdin Theater") == "aladdin"

    def test_removes_theatre(self) -> None:
        assert normalize_venue_name("Hawthorne Theatre") == "hawthorne"

    def test_removes_music_venue(self) -> None:
        assert normalize_venue_name("The Get Down Music Venue") == "the get down"

    def test_removes_at_the_crystal(self) -> None:
        # "Lolas Room At the Crystal" → "lolas room"
        assert normalize_venue_name("Lolas Room At the Crystal") == "lolas room"

    def test_strips_apostrophe(self) -> None:
        # Event venue "Lola's Room" should match SQLite "Lolas Room At the Crystal"
        assert normalize_venue_name("Lola's Room") == "lolas room"

    def test_mcmenamins_al_den(self) -> None:
        # SQLite name is "McMenamins Al's Den" → normalized → "mcmenamins als den"
        assert normalize_venue_name("McMenamins Al's Den") == "mcmenamins als den"
        # Event venue might just be "Al's Den" → "als den"
        assert normalize_venue_name("Al's Den") == "als den"

    def test_lowercase(self) -> None:
        assert normalize_venue_name("Crystal Ballroom") == "crystal ballroom"

    def test_removes_saloon(self) -> None:
        assert normalize_venue_name("McMenamins White Eagle Saloon") == "mcmenamins white eagle"


class TestLookupTravel:
    def _times(self) -> dict:
        return {
            "crystal ballroom": {"minutes": 7, "miles": 2.5},
            "mississippi studios": {"minutes": 3, "miles": 0.9},
            "lolas room": {"minutes": 7, "miles": 2.5},
            "mcmenamins als den": {"minutes": 7, "miles": 2.5},
        }

    def test_exact_match(self) -> None:
        result = lookup_travel("Crystal Ballroom", self._times())
        assert result is not None
        assert result["minutes"] == 7

    def test_apostrophe_venue_matches(self) -> None:
        # "Lola's Room" normalizes to "lolas room" — should match
        result = lookup_travel("Lola's Room", self._times())
        assert result is not None
        assert result["minutes"] == 7

    def test_als_den_substring_match(self) -> None:
        # "Als Den" is a substring of "mcmenamins als den"
        result = lookup_travel("Al's Den", self._times())
        assert result is not None

    def test_unknown_venue_returns_none(self) -> None:
        result = lookup_travel("Some Unknown Bar", self._times())
        assert result is None


class TestDistanceSignal:
    def test_close_venue(self) -> None:
        assert distance_signal(3) == 1.0
        assert distance_signal(10) == 1.0

    def test_near_venue(self) -> None:
        assert distance_signal(11) == 0.5
        assert distance_signal(30) == 0.5

    def test_far_venue(self) -> None:
        assert distance_signal(31) == 0.0
        assert distance_signal(60) == 0.0

    def test_none_is_zero(self) -> None:
        assert distance_signal(None) == 0.0


class TestFallbackDict:
    def test_close_venues_exist(self) -> None:
        # Venues near 5123 N Williams should all be in the fallback
        assert "blue diamond" in _FALLBACK_TRAVEL_MINUTES
        assert "laurelthirst" in _FALLBACK_TRAVEL_MINUTES
        assert "kenton club" in _FALLBACK_TRAVEL_MINUTES

    def test_fallback_minutes_are_reasonable(self) -> None:
        for name, mins in _FALLBACK_TRAVEL_MINUTES.items():
            assert 1 <= mins <= 20, f"{name}: {mins} minutes out of range"

    def test_apostrophe_key_lookable(self) -> None:
        # "kelly's olympian" key has apostrophe; get_travel_times normalizes it
        # so lookup_travel("Kelly's Olympian", ...) must find it.
        from showcat.core.travel import get_travel_times, lookup_travel
        times = {k: v for k, v in get_travel_times().items() if "kelly" in k or "olympian" in k}
        assert times, "Kelly's Olympian should appear in travel_times after normalization"
        result = lookup_travel("Kelly's Olympian", get_travel_times())
        assert result is not None
        assert result["minutes"] == _FALLBACK_TRAVEL_MINUTES["kelly's olympian"]
