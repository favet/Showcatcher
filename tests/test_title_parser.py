"""Tests for the shared title_parser normalization module.

All examples are drawn from the real Portland venue DB audit of 2026-06-21.
"""
import pytest

from showcat.adapters.sources.title_parser import (
    clean_whitespace,
    decode_html,
    extract_status,
    extract_w_opener,
    is_non_show,
    normalize_title,
    split_multi_artist_comma,
    split_multi_artist_plus,
    strip_age_suffix,
    strip_paren_night,
    strip_tour_suffix,
)


# ─────────────────────────────────────────────────────────────────────────────
# is_non_show
# ─────────────────────────────────────────────────────────────────────────────

class TestIsNonShow:
    def test_bridgetown_trivia(self):
        assert is_non_show("Bridgetown Trivia")
        assert is_non_show("bridgetown trivia")

    def test_no_fun_karaoke(self):
        assert is_non_show("No Fun Karaoke")

    def test_rip_city_bingo(self):
        assert is_non_show("Rip City Music Bingo")
        assert is_non_show("RIP City Bingo-oke")

    def test_trivia_with(self):
        assert is_non_show("Trivia with TJ")

    def test_closed_all_day(self):
        assert is_non_show("Closed all day for private event")

    def test_private_event(self):
        assert is_non_show("private event")

    def test_outdoor_early(self):
        assert is_non_show("Outdoor early")

    def test_indoor_evening(self):
        assert is_non_show("Indoor evening")

    def test_kenton_address(self):
        assert is_non_show("2025 N Kilpatrick St, Portland, OR 97217")

    def test_kenton_email(self):
        assert is_non_show("wfkcbooking @gmail.com")

    def test_karaoke_from_hell(self):
        assert is_non_show("KARAOKE FROM HELL")

    def test_two_step_tuesday(self):
        assert is_non_show("Two-Step Tuesday with The Evangeliners and Dance Lessons")

    # Negative cases — real shows that must NOT be filtered
    def test_pavement_passes(self):
        assert not is_non_show("Pavement")

    def test_nofunbar_live_passes(self):
        assert not is_non_show("No Fun Bar Live Music")

    def test_girli_passes(self):
        assert not is_non_show("Girli – w/ Creature Party – All Ages")

    def test_holocene_show_passes(self):
        assert not is_non_show("Slow Magic  – 21+")

    def test_whiskey_wednesday_filters(self):
        assert is_non_show("Whiskey Wednesday with The Neon Prairie Dogs")


# ─────────────────────────────────────────────────────────────────────────────
# decode_html
# ─────────────────────────────────────────────────────────────────────────────

class TestDecodeHtml:
    def test_amp(self):
        assert decode_html("Brian Fallon &amp; The Painkillers") == "Brian Fallon & The Painkillers"

    def test_apos(self):
        assert decode_html("Music for the Masses: Dark 80&#39;s New Wave Nite") == "Music for the Masses: Dark 80's New Wave Nite"

    def test_get_down(self):
        assert decode_html("Deadhead Disco: Jerry&#39;s Birthday Celebration") == "Deadhead Disco: Jerry's Birthday Celebration"

    def test_no_entities_unchanged(self):
        assert decode_html("Pavement") == "Pavement"

    def test_gt_lt(self):
        assert decode_html("A &lt; B &gt; C") == "A < B > C"


# ─────────────────────────────────────────────────────────────────────────────
# clean_whitespace
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanWhitespace:
    def test_nbsp(self):
        assert clean_whitespace("Anna\xa0von\xa0Hausswolff") == "Anna von Hausswolff"

    def test_zwsp(self):
        assert clean_whitespace("Hello\u200bWorld") == "HelloWorld"

    def test_double_space(self):
        assert clean_whitespace("Slow Magic  ") == "Slow Magic"

    def test_thin_space(self):
        assert clean_whitespace("CLUB\u2009SLAYYY") == "CLUB SLAYYY"

    def test_already_clean(self):
        assert clean_whitespace("Pavement") == "Pavement"


# ─────────────────────────────────────────────────────────────────────────────
# extract_status
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractStatus:
    def test_sold_out_colon(self):
        title, status = extract_status("SOLD OUT: Pavement")
        assert title == "Pavement"
        assert status == "sold_out"

    def test_sold_out_space(self):
        title, status = extract_status("SOLD OUT: The Hold Steady: Boys and Girls in America 20")
        assert title == "The Hold Steady: Boys and Girls in America 20"
        assert status == "sold_out"

    def test_sold_out_kurt_vile(self):
        title, status = extract_status("SOLD OUT: Kurt Vile And The Violators")
        assert title == "Kurt Vile And The Violators"
        assert status == "sold_out"

    def test_cancelled_asterisks(self):
        title, status = extract_status("*CANCELLED* 3QUENCY – GIRLS TALK TOUR")
        assert status == "cancelled"
        assert "3QUENCY" in title

    def test_moved_to_roseland(self):
        title, status = extract_status("MOVED TO ROSELAND THEATER: Julia Wolf – Deep End World Tour")
        assert status == "moved"
        assert "Julia Wolf" in title

    def test_moved_to_crystal(self):
        title, status = extract_status("MOVED TO THE CRYSTAL BALLROOM: Slayyyter – WOR$T GIRL IN THE WORLD TOUR")
        assert status == "moved"
        assert "Slayyyter" in title

    def test_no_prefix_returns_none(self):
        title, status = extract_status("Pavement")
        assert title == "Pavement"
        assert status is None

    def test_normal_colon_not_stripped(self):
        # "Artist: Subtitle" — no status keyword, should not be stripped
        title, status = extract_status("Lucero: Celebrating 'That Much Further West'")
        assert status is None
        assert title == "Lucero: Celebrating 'That Much Further West'"


# ─────────────────────────────────────────────────────────────────────────────
# strip_age_suffix
# ─────────────────────────────────────────────────────────────────────────────

class TestStripAgeSuffix:
    def test_21_plus(self):
        assert strip_age_suffix("Slow Magic  – 21+") == "Slow Magic"

    def test_18_plus(self):
        assert strip_age_suffix("2charm – 18+") == "2charm"

    def test_21_plus_event(self):
        assert strip_age_suffix("Emo Nite at Holocene presented by Emo Nite LA – 21+ event") == "Emo Nite at Holocene presented by Emo Nite LA"

    def test_all_ages(self):
        assert strip_age_suffix("Girli – All Ages") == "Girli"

    def test_all_ages_exclamation(self):
        assert strip_age_suffix("Failboat & Jaymoji: The Stupid Simple Gameshow – ALL AGES!") == "Failboat & Jaymoji: The Stupid Simple Gameshow"

    def test_early_show(self):
        assert strip_age_suffix("Holland Andrews + Methods Body – Record Release Party – EARLY SHOW!") == "Holland Andrews + Methods Body – Record Release Party"

    def test_no_suffix_unchanged(self):
        assert strip_age_suffix("Pavement") == "Pavement"

    def test_multi_artist_comma_preserved(self):
        # "Casket Cassette, Stare Away – 21+" → just the 21+ suffix stripped
        result = strip_age_suffix("Casket Cassette, Stare Away – 21+")
        assert result == "Casket Cassette, Stare Away"


# ─────────────────────────────────────────────────────────────────────────────
# strip_tour_suffix
# ─────────────────────────────────────────────────────────────────────────────

class TestStripTourSuffix:
    def test_simple_tour(self):
        assert strip_tour_suffix("Anthony Green - This Tour Won't Save You") == "Anthony Green"

    def test_em_dash_tour(self):
        assert strip_tour_suffix("Fulton Lee – Sing With Me Tour 2026") == "Fulton Lee"

    def test_anniversary_tour(self):
        assert strip_tour_suffix("WOLFMOTHER – 20th Anniversary Tour") == "WOLFMOTHER"

    def test_world_tour(self):
        assert strip_tour_suffix("Waylon Wyatt – Dustpiles World Tour") == "Waylon Wyatt"

    def test_deep_end_world_tour(self):
        assert strip_tour_suffix("Julia Wolf – Deep End World Tour") == "Julia Wolf"

    def test_lp_tour(self):
        assert strip_tour_suffix("LP – All Is Not Lost Tour") == "LP"

    def test_katietpruitt(self):
        assert strip_tour_suffix("Katie Pruitt - Fools For The Fleeting Tour") == "Katie Pruitt"

    def test_ella_red_part(self):
        assert strip_tour_suffix("Ella Red - TOUR'S NOT REAL: PART 2") == "Ella Red"

    def test_ampersand_coheadliner_not_stripped(self):
        # "Benjamin Tod & Lost Dog Street Band" — ampersand guard
        result = strip_tour_suffix("Benjamin Tod & Lost Dog Street Band")
        assert result == "Benjamin Tod & Lost Dog Street Band"

    def test_no_suffix_unchanged(self):
        assert strip_tour_suffix("Pavement") == "Pavement"

    def test_sim_world_tour(self):
        assert strip_tour_suffix("SiM – HOOMAN WORLD TOUR") == "SiM"


# ─────────────────────────────────────────────────────────────────────────────
# strip_paren_night
# ─────────────────────────────────────────────────────────────────────────────

class TestStripParenNight:
    def test_night_1(self):
        assert strip_paren_night("Pedro the Lion (Night 1)") == "Pedro the Lion"

    def test_night_2(self):
        assert strip_paren_night("Benjamin Tod & Lost Dog Street Band (Night 2)") == "Benjamin Tod & Lost Dog Street Band"

    def test_show_suffix(self):
        assert strip_paren_night("Artist (Show 3)") == "Artist"

    def test_no_paren_unchanged(self):
        assert strip_paren_night("Pavement") == "Pavement"

    def test_paren_that_is_not_night(self):
        # "(of La Femme)" is NOT a night suffix — should be preserved
        result = strip_paren_night("Marlon Magnée (of La Femme)")
        assert result == "Marlon Magnée (of La Femme)"


# ─────────────────────────────────────────────────────────────────────────────
# extract_w_opener
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractWOpener:
    def test_basic_w_slash(self):
        headliner, opener = extract_w_opener("Girli – w/ Creature Party – All Ages")
        assert headliner == "Girli"
        assert opener == "Creature Party"

    def test_w_slash_no_space(self):
        headliner, opener = extract_w_opener("Pixel Grip (DJ Set) w/ Sharlese- 21+")
        assert headliner == "Pixel Grip (DJ Set)"
        assert opener == "Sharlese"

    def test_ivri_tour_w_opener(self):
        headliner, opener = extract_w_opener('ivri: The "Evidence of you" Tour w/Forest – All Ages!')
        # headliner should have tour stripped later; w_opener extracts Forest
        assert opener == "Forest"

    def test_jejune_w_racecourse(self):
        headliner, opener = extract_w_opener("Jejune w/ Racecourse")
        assert headliner == "Jejune"
        assert opener == "Racecourse"

    def test_matthew_dear(self):
        headliner, opener = extract_w_opener("Matthew Dear (DJ set) – w/ Feu du Camp & Trustfall – 21+")
        assert headliner == "Matthew Dear (DJ set)"
        # opener could be "Feu du Camp & Trustfall" — multi-artist string, accept it
        assert opener is not None
        assert "Feu du Camp" in opener

    def test_no_w_slash_unchanged(self):
        headliner, opener = extract_w_opener("Pavement")
        assert headliner == "Pavement"
        assert opener is None

    def test_tba_opener_returns_none(self):
        headliner, opener = extract_w_opener("Artist w/ TBA")
        assert headliner == "Artist"
        assert opener is None


# ─────────────────────────────────────────────────────────────────────────────
# normalize_title — integration
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeTitle:
    def test_tour_suffix_stripped(self):
        headliner, openers, status = normalize_title("Anthony Green - This Tour Won't Save You")
        assert headliner == "Anthony Green"
        assert status is None

    def test_age_suffix_stripped(self):
        headliner, openers, status = normalize_title("Slow Magic  – 21+")
        assert headliner == "Slow Magic"
        assert status is None

    def test_sold_out_prefix(self):
        headliner, openers, status = normalize_title("SOLD OUT: Pavement")
        assert headliner == "Pavement"
        assert status == "sold_out"

    def test_cancelled_prefix(self):
        headliner, openers, status = normalize_title("*CANCELLED* 3QUENCY – GIRLS TALK TOUR")
        assert status == "cancelled"

    def test_moved_prefix(self):
        headliner, openers, status = normalize_title(
            "MOVED TO THE CRYSTAL BALLROOM: Slayyyter – WOR$T GIRL IN THE WORLD TOUR"
        )
        assert status == "moved"
        assert "Slayyyter" in headliner

    def test_w_opener_extracted(self):
        headliner, openers, status = normalize_title("Girli – w/ Creature Party – All Ages")
        assert headliner == "Girli"
        assert "Creature Party" in openers

    def test_html_decoded(self):
        headliner, openers, status = normalize_title("Brian Fallon &amp; The Painkillers")
        assert headliner == "Brian Fallon & The Painkillers"

    def test_nbsp_cleaned(self):
        headliner, openers, status = normalize_title("Anna\xa0von\xa0Hausswolff")
        assert headliner == "Anna von Hausswolff"

    def test_paren_night_stripped(self):
        headliner, openers, status = normalize_title("Pedro the Lion (Night 1)")
        assert headliner == "Pedro the Lion"

    def test_tour_plus_age(self):
        # Both tour suffix and age suffix present
        headliner, openers, status = normalize_title(
            "ILUKA – The Wings Tour – All Ages"
        )
        assert headliner == "ILUKA"

    def test_existing_openers_preserved(self):
        headliner, openers, status = normalize_title(
            "Girli – w/ Creature Party",
            existing_openers=["Support Act"],
        )
        assert "Support Act" in openers
        assert "Creature Party" in openers

    def test_w_opener_not_duplicated(self):
        headliner, openers, status = normalize_title(
            "Girli – w/ Creature Party",
            existing_openers=["Creature Party"],
        )
        assert openers.count("Creature Party") == 1

    def test_holocene_complex(self):
        # "Otha: Club 20 Tour 2026 – w/ Digital Warthog – 21+"
        headliner, openers, status = normalize_title(
            "Otha: Club 20 Tour 2026 – w/ Digital Warthog – 21+"
        )
        assert headliner == "Otha"
        assert "Digital Warthog" in openers


# ─────────────────────────────────────────────────────────────────────────────
# split_multi_artist_plus
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitMultiArtistPlus:
    def test_two_bands_plus(self):
        headliner, openers = split_multi_artist_plus("Blue Flags Black Grass + Dumpster Joe & The Boys")
        assert headliner == "Blue Flags Black Grass"
        assert "Dumpster Joe & The Boys" in openers

    def test_three_bands_plus(self):
        headliner, openers = split_multi_artist_plus("The Blurry Stars + Die Right + Fawkes Glove")
        assert headliner == "The Blurry Stars"
        assert "Die Right" in openers
        assert "Fawkes Glove" in openers

    def test_tba_dropped(self):
        headliner, openers = split_multi_artist_plus("Machete Mouth + TBA")
        assert headliner == "Machete Mouth"
        assert openers == []

    def test_slash_separated(self):
        headliner, openers = split_multi_artist_plus("Beezlebabes/Baby Graves/Velvet Merkin")
        assert headliner == "Beezlebabes"
        assert "Baby Graves" in openers

    def test_no_separator_unchanged(self):
        headliner, openers = split_multi_artist_plus("Pavement")
        assert headliner == "Pavement"
        assert openers == []

    def test_existing_openers_extended(self):
        headliner, openers = split_multi_artist_plus(
            "Band A + Band B",
            existing_openers=["Band C"],
        )
        assert "Band C" in openers
        assert "Band B" in openers


# ─────────────────────────────────────────────────────────────────────────────
# split_multi_artist_comma
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitMultiArtistComma:
    def test_three_part_comma(self):
        headliner, openers = split_multi_artist_comma(
            "Madi Gaines, Chipped Nail Polish, Myriads"
        )
        assert headliner == "Madi Gaines"
        assert "Chipped Nail Polish" in openers
        assert "Myriads" in openers

    def test_two_part_not_split_default(self):
        # Default min_parts=3 means 2-part is left alone
        headliner, openers = split_multi_artist_comma("Casket Cassette, Stare Away")
        assert headliner == "Casket Cassette, Stare Away"
        assert openers == []

    def test_two_part_split_if_min_2(self):
        # Explicitly override min_parts
        headliner, openers = split_multi_artist_comma(
            "Casket Cassette, Stare Away", min_parts=2
        )
        assert headliner == "Casket Cassette"
        assert "Stare Away" in openers

    def test_tba_dropped(self):
        headliner, openers = split_multi_artist_comma("Band A, Band B, TBA", min_parts=2)
        assert "TBA" not in openers

    def test_no_comma_unchanged(self):
        headliner, openers = split_multi_artist_comma("Pavement")
        assert headliner == "Pavement"
        assert openers == []

    def test_long_part_not_split(self):
        # One of the parts is too long to be a band name (>5 words) — skip split
        result_h, result_o = split_multi_artist_comma(
            "Short Name, This Is A Very Long Event Description With Many Words, Another Band"
        )
        assert result_o == []
