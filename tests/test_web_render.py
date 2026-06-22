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
        "is_placeholder_link": False,
        "score_total": 0.5,
        "matched_artist": None,
        "spotify_url": None,
        "event_spotify_url": None,
        "spotify_artist_image_url": None,
        "spotify_album_image_url": None,
        "event_image_url": None,
        "price": None,
        "openers": [],
        "album_name": None,
        "travel_minutes": None,
        "genres": [],
        "description": None,
        "source": "aladdin_theater",
        "timestamp": 0,
    }
    base.update(kw)
    return base


def test_render_includes_provider_label_and_via_markup() -> None:
    html = render_html([_show()], dt.datetime(2026, 6, 21, 12, 0))
    assert "tix-pill" in html
    assert "ticket_provider_label" in html
    assert '"ticket_provider": "etix"' in html
    assert "Etix" in html


def test_render_is_valid_nonempty_html() -> None:
    html = render_html([_show()], dt.datetime(2026, 6, 21, 12, 0))
    assert html.startswith("<!DOCTYPE html>")
    assert "American Aquarium" in html
    assert '"headliner": "American Aquarium"' in html


def test_etix_show_is_not_placeholder() -> None:
    html = render_html([_show()], dt.datetime(2026, 6, 21, 12, 0))
    assert '"is_placeholder_link": false' in html


def test_tm_show_is_placeholder() -> None:
    show = _show(
        ticket_url="https://www.ticketmaster.com/event/xyz",
        ticket_provider="ticketmaster",
        ticket_provider_label="Ticketmaster",
        is_placeholder_link=True,
    )
    html = render_html([show], dt.datetime(2026, 6, 21, 12, 0))
    assert '"is_placeholder_link": true' in html


def test_favicon_present() -> None:
    html = render_html([_show()], dt.datetime(2026, 6, 21, 12, 0))
    assert "rel=\"icon\"" in html


def test_pictured_pct_stat_in_template() -> None:
    html = render_html([_show()], dt.datetime(2026, 6, 21, 12, 0))
    assert "picturedPct" in html
    assert "hs-pictured" in html
    assert "hs-scored" not in html
