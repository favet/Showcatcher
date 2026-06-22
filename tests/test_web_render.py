"""Phase 8.5 — web output renders the ticket-provider badge."""
import datetime as dt

from showcat.outputs.web.adapter import render_html


def _show(**kw: object) -> dict:
    base = {
        "id": 1,
        "headliner": "American Aquarium",
        "venue": "Aladdin Theater",
        "date": "2026-09-19",
        "date_display": "Sat Sep 19",
        "doors_display": None,
        "show_display": "8:00 PM",
        "ticket_url": "https://www.etix.com/ticket/p/36904187/american-aquarium",
        "ticket_provider": "etix",
        "ticket_provider_label": "Etix",
        "score_total": 0.5,
        "matched_artist": None,
        "travel_minutes": None,
        "genres": [],
        "source": "aladdin_theater",
        "timestamp": 0,
    }
    base.update(kw)
    return base


def test_render_includes_provider_label_and_via_markup() -> None:
    html = render_html([_show()], dt.datetime(2026, 6, 21, 12, 0))
    # The Vue template + data both ship in the page; the badge wiring is present.
    assert "tix-pill" in html
    assert "ticket_provider_label" in html
    assert '"ticket_provider": "etix"' in html
    assert "Etix" in html


def test_render_is_valid_nonempty_html() -> None:
    html = render_html([_show()], dt.datetime(2026, 6, 21, 12, 0))
    assert html.startswith("<!DOCTYPE html>")
    assert "American Aquarium" in html
    # The show payload is embedded as JSON for the Vue app to consume.
    assert '"headliner": "American Aquarium"' in html
