"""Team event filter helpers."""

from prizepicks_oddsshark.client import OddsClient
from prizepicks_oddsshark.matching import team_filter_applies


def test_team_filter_applies_college_only():
    assert team_filter_applies("americanfootball_ncaaf") is True
    assert team_filter_applies("basketball_ncaab") is True
    assert team_filter_applies("americanfootball_nfl") is False
    assert team_filter_applies("basketball_nba") is False


def test_fetch_filters_events_by_team(monkeypatch):
    client = OddsClient(demo=False, api_key="test")
    events = [
        {"id": "1", "home_team": "Nebraska Cornhuskers", "away_team": "Iowa Hawkeyes"},
        {"id": "2", "home_team": "Ohio State Buckeyes", "away_team": "Michigan Wolverines"},
    ]
    monkeypatch.setattr(client, "list_events", lambda sport: events)

    captured = {}

    def fake_odds(sport, event_id, **kwargs):
        captured["event_id"] = event_id
        return {"id": event_id, "bookmakers": []}

    monkeypatch.setattr(client, "event_odds", fake_odds)
    out = client.fetch_prop_events(
        "americanfootball_ncaaf",
        ["player_pass_yds"],
        max_events=5,
        include_alternates=False,
        team="Nebraska",
    )
    assert len(out) == 1
    assert captured["event_id"] == "1"
