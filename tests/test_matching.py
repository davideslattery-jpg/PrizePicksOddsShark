from prizepicks_oddsshark.matching import (
    canonical_market,
    classify_prizepicks_tier,
    extract_props_from_event,
    index_book_props,
    nearest_book_leg,
    normalize_name,
)


def test_normalize_name_accents_and_suffix():
    assert normalize_name("Nikola Jokić Jr.") == "nikola jokic"
    assert normalize_name("Jayson Tatum") == "jayson tatum"


def test_canonical_market_strips_alternate():
    assert canonical_market("player_points_alternate") == "player_points"
    assert canonical_market("pra") == "player_points_rebounds_assists"


def test_classify_tiers():
    assert classify_prizepicks_tier("player_points", -137) == "standard"
    assert classify_prizepicks_tier("player_points_alternate", 100) == "demon"
    assert classify_prizepicks_tier("player_points_alternate", -250) == "goblin"


SAMPLE_EVENT = {
    "id": "e1",
    "sport_key": "basketball_nba",
    "commence_time": "2026-09-11T02:00:00Z",
    "home_team": "A",
    "away_team": "B",
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over", "description": "LeBron James", "price": -110, "point": 24.5},
                        {"name": "Under", "description": "LeBron James", "price": -110, "point": 24.5},
                        {"name": "Over", "description": "LeBron James", "price": -120, "point": 25.5},
                        {"name": "Under", "description": "LeBron James", "price": 100, "point": 25.5},
                    ],
                }
            ],
        },
        {
            "key": "prizepicks",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over", "description": "LeBron James", "price": -137, "point": 24.5},
                    ],
                },
                {
                    "key": "player_points_alternate",
                    "outcomes": [
                        {"name": "Over", "description": "LeBron James", "price": 100, "point": 30.5},
                    ],
                },
            ],
        },
    ],
}


def test_extract_and_nearest_line():
    fd = extract_props_from_event(SAMPLE_EVENT, bookmaker_keys=["fanduel"])
    pp = extract_props_from_event(SAMPLE_EVENT, bookmaker_keys=["prizepicks"])
    assert any(p.tier == "demon" for p in pp)
    assert any(p.tier == "standard" for p in pp)

    idx = index_book_props(fd)
    cands = idx[("lebron james", "player_points", "Over")]
    nearest = nearest_book_leg(cands, 24.5)
    assert nearest is not None
    assert nearest.point == 24.5
    nearest2 = nearest_book_leg(cands, 25.0)
    assert nearest2 is not None
    assert nearest2.point in (24.5, 25.5)
