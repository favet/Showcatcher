"""Phase 8.4 — cross-source show merge + ticket-link preference."""
from showcat.outputs.web.adapter import canonical_show_key, merge_shows_by_identity


def _show(**kw: object) -> dict:
    base = {
        "headliner": "Some Band",
        "venue": "Aladdin Theater",
        "date": "2026-09-19",
        "ticket_url": None,
        "score_total": None,
    }
    base.update(kw)
    return base


class TestCanonicalKey:
    def test_same_show_different_sources_same_key(self) -> None:
        a = canonical_show_key("Aladdin Theater", "2026-09-19", "American Aquarium")
        b = canonical_show_key("aladdin theater", "2026-09-19", "American Aquarium")
        assert a == b

    def test_different_date_different_key(self) -> None:
        a = canonical_show_key("Aladdin Theater", "2026-09-19", "X")
        b = canonical_show_key("Aladdin Theater", "2026-09-20", "X")
        assert a != b


class TestMergePreference:
    def test_etix_supersedes_ticketmaster_for_same_show(self) -> None:
        tm = _show(
            ticket_url="https://www.ticketmaster.com/event/abc",
            source="ticketmaster",
            score_total=0.9,
        )
        etix = _show(
            ticket_url="https://www.etix.com/ticket/p/36904187/american-aquarium",
            source="aladdin_theater",
            score_total=None,
        )
        merged = merge_shows_by_identity([tm, etix])
        assert len(merged) == 1
        assert merged[0]["ticket_provider"] == "etix"
        assert "etix.com" in merged[0]["ticket_url"]
        # representative keeps the higher score (from the TM-scored row)
        assert merged[0]["score_total"] == 0.9

    def test_tm_only_show_keeps_tm_link(self) -> None:
        tm = _show(
            headliner="TM Only Band",
            ticket_url="https://www.ticketmaster.com/event/zzz",
            source="ticketmaster",
        )
        merged = merge_shows_by_identity([tm])
        assert len(merged) == 1
        assert merged[0]["ticket_provider"] == "ticketmaster"
        assert "ticketmaster.com" in merged[0]["ticket_url"]

    def test_distinct_shows_not_merged(self) -> None:
        a = _show(headliner="Band A", ticket_url="https://etix.com/a")
        b = _show(headliner="Band B", ticket_url="https://etix.com/b")
        merged = merge_shows_by_identity([a, b])
        assert len(merged) == 2

    def test_provider_label_attached(self) -> None:
        etix = _show(ticket_url="https://www.etix.com/ticket/p/1/x")
        merged = merge_shows_by_identity([etix])
        assert merged[0]["ticket_provider_label"] == "Etix"

    def test_custom_price_precedence_over_ticketmaster(self) -> None:
        tm = _show(
            ticket_url="https://www.ticketmaster.com/event/abc",
            source="ticketmaster",
            price="$30.00 - $50.00",
        )
        venue = _show(
            ticket_url="https://www.etix.com/ticket/p/1/x",
            source="aladdin_theater",
            price="$25.00",
        )
        merged = merge_shows_by_identity([tm, venue])
        assert len(merged) == 1
        assert merged[0]["price"] == "$25.00"

    def test_placeholder_link_detected(self) -> None:
        tm_no_price = _show(
            ticket_url="https://www.ticketmaster.com/event/abc",
            source="ticketmaster",
            price=None,
        )
        merged = merge_shows_by_identity([tm_no_price])
        assert len(merged) == 1
        assert merged[0]["is_placeholder_link"] is True

        # TM with a price is still a TM-family redirect (aggregator) → placeholder.
        tm_with_price = _show(
            ticket_url="https://www.ticketmaster.com/event/abc",
            source="ticketmaster",
            price="$25.00",
        )
        merged2 = merge_shows_by_identity([tm_with_price])
        assert len(merged2) == 1
        assert merged2[0]["is_placeholder_link"] is True
