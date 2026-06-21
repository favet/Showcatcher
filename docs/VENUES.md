# Portland Venues — Showcat Coverage Inventory

> Last updated: 2026-06-21. This is a living doc — mark scrape status as work proceeds.
> **Verified TM IDs** were confirmed via live Ticketmaster API (`/venues.json?keyword=...&stateCode=OR`).
> Capacity, ticketer, and show URLs for non-TM venues are from research/training data — cross-check before building adapters.

> ## ⚠️ Phase 8 ticketer correction (2026-06-21, verified via live venue sites)
> The "Ticketer" column below was substantially **wrong** — it listed Ticketmaster/Dice/Eventbrite
> for venues that actually sell through **Etix**. Ticketmaster's Discovery API merely *aggregates/resells*
> these shows; the venues' own "Buy Tickets" links go to `etix.com` (URLs look like
> `https://www.etix.com/ticket/p/<id>/<slug>?partner_id=100`).
>
> **Verified Etix (checked live 2026-06-21):** Crystal Ballroom, Aladdin Theater, Roseland Theater,
> Hawthorne Theatre, Mississippi Studios, Polaris Hall, Holocene, Alberta Rose Theatre.
> **Strongly implied Etix (same operators / McMenamins-Etix):** Wonder Ballroom, Doug Fir, Revolution
> Hall, Lola's Room, White Eagle, Al's Den, Edgefield.
> Net effect: the planned Dice/Eventbrite adapters are mostly unnecessary — **one Etix adapter covers the
> majority of dedicated venues.** TM stays only as a discovery safety-net + last-resort link.

## How to use this doc

| Column | Meaning |
|---|---|
| **Live Venue?** | `Dedicated` = primary focus is live music, `Occasional/Bar` = bar/restaurant/space that hosts live music, `Festival` = outdoor/event-based |
| **Active** | ✓ = currently booking shows, `seasonal` = runs part of the year, ? = uncertain/unconfirmed, ✗ = closed |
| **Ticketer** | Primary ticketing platform |
| **TM ID** | Ticketmaster venue ID. "verified" = confirmed via live API. "unknown" = likely on TM but ID not yet looked up. "N/A" = not on Ticketmaster |
| **Show URL** | Canonical URL for their upcoming shows listing |
| **Scrape** | ✓ ingested / 🔄 in progress / ○ not yet / ✗ blocked |

---

## Large venues (>1,000 capacity)

| Venue | Neighborhood | Cap | Genre | Live Venue? | Active | Ticketer | TM ID | Show URL | Scrape |
|---|---|---|---|---|---|---|---|---|---|
| Arlene Schnitzer Concert Hall | Downtown | 2,776 | Classical, pop, touring | Dedicated | ✓ | Ticketmaster / Portland'5 | `KovZpZAEkkJA` **verified** | portland5.org/arlene-schnitzer-concert-hall | ✓ |
| Keller Auditorium | Downtown | 2,992 | Broadway, opera, ballet | Dedicated | ✓ | Ticketmaster / Portland'5 | `KovZpZAEkdFA` **verified** | portland5.org/keller-auditorium | ○ |
| Moda Center | Rose Quarter | 19,393 | Arena rock, hip-hop, pop | Dedicated | ✓ | Ticketmaster | `KovZpa6MXe` **verified** | rosequarter.com/moda-center | ○ |
| Veterans Memorial Coliseum | Rose Quarter | 12,000 | Mid-size arena acts | Dedicated | ✓ | Ticketmaster | `KovZpZAJ67kA` **verified** | rosequarter.com/veterans-memorial-coliseum | ○ |
| McMenamins Edgefield Amphitheater | Troutdale | ~5,000 | Rock, folk, pop (summer only) | Dedicated | seasonal | Ticketmaster / McMenamins | `KovZpZA1vFlA` **verified** | mcmenamins.com/edgefield | ○ |
| Crystal Ballroom | Downtown | 1,500 | All genres, indie/alt | Dedicated | ✓ | **Etix** ✓verified | `rZ7HnEZaeyv` **verified** | crystalballroompdx.com | ✓ |
| Roseland Theater | Downtown | 1,400 | Rock, metal, hip-hop | Dedicated | ✓ | **Etix** ✓verified | `KovZpap9re` **verified** | roselandpdx.com | ✓ |

---

## Mid-size venues (300–1,000 capacity)

| Venue | Neighborhood | Cap | Genre | Live Venue? | Active | Ticketer | TM ID | Show URL | Scrape |
|---|---|---|---|---|---|---|---|---|---|
| Revolution Hall | Buckman | 850 | Indie, rock, eclectic | Dedicated | ✓ | Ticketmaster | `KovZpZAEkdIA` **verified** | revolutionhall.com | ✓ |
| Hawthorne Theatre | Hawthorne / Buckman | 750 | Rock, metal, punk | Dedicated | ✓ | **Etix** ✓verified | `KovZpZAkn7IA` **verified** | hawthornetheater.com | ✓ |
| Aladdin Theater | Sellwood-Moreland | 620 | Americana, folk, world | Dedicated | ✓ | **Etix** ✓verified | `KovZpa3qfe` **verified** | aladdin-theater.com | ✓ |
| Wonder Ballroom | Alberta Arts District | 650 | Indie, rock, folk | Dedicated | ✓ | Ticketmaster | `KovZpa9hBe` **verified** | wonderballroom.com | ✓ |
| Bossanova Ballroom | Central Eastside | ~700 | Dance, electronic, events | Dedicated | ✓ | Tixr / Ticket Fairy | N/A | novapdx.com | ○ |
| Polaris Hall | Central Eastside | ~500 | Electronic, dance, DJ | Dedicated | ✓ | **Etix** ✓verified | `Z7r9jZadc-` **verified** | polarishallpdx.com | ○ |
| Star Theater | Old Town | ~350 | Rock, alternative, punk | Dedicated | ✓ | Ticketmaster | `KovZpZAIvlnA` **verified** | startheaterportland.com | ○ |
| Lola's Room | Downtown | ~400 | Pop, dance, indie | Dedicated | ✓ | Ticketmaster | `KovZpZA1vlJA` **verified** | crystalballroompdx.com/lolas-room | ○ |
| Alberta Rose Theatre | Alberta Arts District | 350 | Americana, folk, world, jazz | Dedicated | ✓ | **Etix** ✓verified | `KovZ917AcZe` **verified** | albertarosetheatre.com | ○ |
| Holocene | Division / Buckman | ~350 | Electronic, dance, indie | Dedicated | ✓ | **Etix** ✓verified | `KovZpZAaIIaA` **verified** | holocene.org | ○ |
| Newmark Theatre | Downtown | 880 | Dance, chamber, spoken word | Dedicated | ✓ | Portland'5 / TM | `KovZpZA7klvA` **verified** | portland5.org/newmark-theatre | ○ |
| Lincoln Hall (PSU) | Downtown / PSU | 475 | Classical, jazz, eclectic | Dedicated | ✓ | AudienceView / TM | `KovZpap1Ve` **verified** | pdx.edu/arts/events | ○ |
| Alberta Abbey | NE Portland | ~400 | Community arts, jazz, indie | Dedicated | ✓ | Eventbrite / Ticketmaster | `Z7r9jZakFN` **verified** | albertaabbey.org | ○ |
| The Get Down | Central Eastside | ~400 | Funk, soul, electronic | Dedicated | ✓ | Ticketweb / Ticketmaster | `Z7r9jZa7Ur` **verified** | thegetdownpdx.com | ○ |
| The Showdown | SE Portland | ~300 | Country, Americana, folk | Dedicated | ✓ | Etix / Ticketmaster | `Z7r9jZaAf-` **verified** | showdownpdx.com | ○ |
| 45 East | Central Eastside | ~800 | Electronic, dance, DJ | Dedicated | ✓ | Tixr / Ticketmaster | `Z7r9jZad7E` **verified** | 45eastpdx.com | ○ |

---

## Small / intimate venues (<300 capacity)

| Venue | Neighborhood | Cap | Genre | Live Venue? | Active | Ticketer | TM ID | Show URL | Scrape |
|---|---|---|---|---|---|---|---|---|---|
| Doug Fir Lounge | Lower Burnside | 300 | Indie, alt, singer-songwriter | Dedicated | ✓ | Ticketmaster | `KovZpZA1k1EA` **verified** | dougfirlounge.com | ✓ |
| Mississippi Studios | Boise-Eliot | 200 | Indie, folk, Americana | Dedicated | ✓ | **Etix** ✓verified | `KovZ917Ai0C` **verified** | mississippistudios.com | ○ |
| Dante's | Old Town | ~300 | Rock, burlesque, metal | Dedicated | ✓ | Eventbrite / Ticketmaster | `KovZpZAEddeA` **verified** | dantespdx.com | ○ |
| McMenamins Kennedy School (theater) | Concordia | ~250 | Acoustic, eclectic | Dedicated | ✓ | McMenamins own site | N/A | mcmenamins.com/kennedy-school | ○ |
| Bunk Bar | Central Eastside | ~200 | Rock, indie, eclectic | Occasional/Bar | ✗ | Eventbrite / own site | N/A | bunkbar.com | ✗ |
| Jack London Revue | Downtown | ~150 | Jazz, blues, eclectic | Dedicated/Basement | ✓ | TicketWeb / TM | `KovZpZAkttkA` **verified** | jacklondonrevue.com | ○ |
| Kelly's Olympian | Downtown | ~150 | Rock, punk, bar shows | Occasional/Bar | ✓ | WordPress (Tribe API) | N/A | kellysolympian.com | ○ |
| Turn! Turn! Turn! | Boise-Eliot | ~100 | Indie, experimental, DIY | Occasional/Bar | ? | Door / own site | N/A | turnturnturnnpdx.com | ○ |
| White Eagle Saloon | N Portland | ~200 | McMenamins live stage | Dedicated | ✓ | McMenamins / Ticketmaster | `KovZpZAFFEdA` **verified** | mcmenamins.com/white-eagle-saloon-hotel | ○ |
| Al's Den | Downtown | ~100 | Acoustic, indie, local | Dedicated/Basement | ✓ | McMenamins / Ticketmaster | `Z7r9jZaA2K` **verified** | mcmenamins.com/crystal-hotel/als-den | ○ |
| The Old Church | Downtown | ~300 | Acoustic, folk, classical | Dedicated | ✓ | Etix / Ticketmaster | `KovZpap53e` **verified** | theoldchurch.org | ○ |
| The Coffin Club | SE Portland | ~150 | Goth, industrial, punk | Dedicated | ✓ | Ticketleap / Ticketmaster | `Z7r9jZaA1l` **verified** | thecoffinclubpdx.com | ○ |
| Twilight Cafe | SE Portland | ~100 | Rock, punk, metal | Occasional/Bar | ✓ | Door / Ticketmaster | `Z7r9jZa7sW` **verified** | twilightcafeandbar.com | ○ |
| Alberta Street Pub | NE Portland | ~150 | Acoustic, Americana, pub | Occasional/Bar | ✓ | Own site / Ticketleap | N/A | albertastreetpub.com | ○ |
| Artichoke Music | SE Portland | ~100 | Acoustic, folk, community | Dedicated | ✓ | Own site | N/A | artichokemusic.org | ○ |
| Blue Diamond | NE Portland | ~100 | Jazz, blues, pub stage | Occasional/Bar | ✓ | None / Door | N/A | bluediamondpdx.com | ✓ |
| LaurelThirst Public House | NE Portland | ~150 | Bluegrass, country, folk | Occasional/Bar | ✓ | None / Door | N/A | laurelthirst.com | ✓ |
| Mississippi Pizza | N Portland | ~100 | Acoustic, pub shows, pizza | Occasional/Bar | ✓ | Own site / Door | N/A | mississippipizza.com | ○ |
| Starday Tavern | SE Portland | ~100 | Tavern stage, rock, blues | Occasional/Bar | ✓ | None / Door | N/A | stardaytavern.com | ✓ |
| The Midnight PDX | SE Portland | ~100 | Lounge stage, eclectic | Occasional/Bar | ✓ | Own site | N/A | themidnightsocietypdx.net | ○ |
| World Famous Kenton Club | N Portland | ~150 | Historic dive stage | Occasional/Bar | ✓ | None / Door | N/A | kentonclub.com | ✓ |
| No Fun Bar | SE Hawthorne | ~100 | Bar shows, punk, karaoke | Occasional/Bar | ✓ | None / Door | N/A | nofunportland.com | ✓ |
| The Goodfoot Pub & Lounge | SE Stark | ~150 | Basement lounge, funk, soul | Dedicated | ✓ | Own site / Door | N/A | thegoodfoot.com | ○ |
| The Spare Room | NE Portland | ~200 | Lounge stage, eclectic | Occasional/Bar | ✓ | None / Door | N/A | spareroomrestaurantandlounge.com | ✓ |

---

## Festivals / outdoor (non-fixed venues)

| Venue | Location | Capacity | Genre | Live Venue? | Active | Ticketer | Notes | Scrape |
|---|---|---|---|---|---|---|---|---|
| Pickathon | Happy Valley (Pendarvis Farm) | ~5,000 | Americana, folk, world, indie | Festival | annual | Own site | Multi-day outdoor festival; not a fixed venue | ○ |

---

## Priority for Phase 6 adapter work

**Tier 1 — already ingested via Ticketmaster (8 venues, one adapter):**
Crystal Ballroom, Wonder Ballroom, Roseland, Hawthorne, Aladdin, Revolution Hall, Doug Fir, Arlene Schnitzer.

**Tier 2 — high-value additions (Ticketmaster, direct config additions):**
Moda Center, Veterans Memorial Coliseum, Keller Auditorium, Star Theater, Lola's Room, Edgefield Amphitheater, White Eagle Saloon, Al's Den, The Old Church, The Get Down, The Showdown, Alberta Abbey, Polaris Hall, Alberta Rose Theatre, Holocene, Mississippi Studios, Dante's, Twilight Cafe, The Coffin Club, 45 East, Newmark Theatre, Jack London Revue.
→ Action: Add these verified TM IDs to `TICKETMASTER_VENUE_IDS` in `.env`.

**Tier 3 — non-TM venues requiring separate/JSON-LD/WordPress adapters:**
Alberta Street Pub (JSON-LD), Artichoke Music (JSON-LD), Kelly's Olympian (WordPress Tribe API).
→ Action: Build and deploy `JsonLdAdapter` (which handles generic JSON-LD and WordPress event JSON data).

- Bunk Bar: ✗ Closed permanently in 2019.
- Bossanova Ballroom (Nova PDX): Tixr ticketing (0 TM events, direct curl block/timeout). Skip for now.
- Lincoln Hall (PSU): AudienceView ticketing (0 TM events). Skip for now.
- The Goodfoot Pub & Lounge: Blocks automated requests (HTTP 403). Skip.
- Mississippi Pizza / The Midnight PDX: Probed but lack structured JSON-LD events. Skip.
- Turn! Turn! Turn!: Door-only dive bar. Skip.

**Tier 5 — custom scrapers (WordPress API / DOM):**
- Blue Diamond: ✓ (WordPress Tribe API)
- LaurelThirst Public House: ✓ (DOM EventON JSON-LD)
- No Fun Bar: ✓ (DOM Squarespace)
- Starday Tavern: ✓ (DOM Elementor Events)
- World Famous Kenton Club: ✓ (DOM plain text)
- The Spare Room: ✓ (DOM plain text)

---

## Ticketmaster ID lookup procedure

To find a TM venue ID for any venue:
```
GET https://app.ticketmaster.com/discovery/v2/venues.json?apikey=<KEY>&keyword=<VENUE_NAME>&stateCode=OR
```
The `id` field in the response is the TM venue ID. Add it to `TICKETMASTER_VENUE_IDS` in `.env`.
