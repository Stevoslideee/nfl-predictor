import live


def test_find_game_id_matches_either_order():
    games = [{"game_id": "1", "home_team": "BUF", "away_team": "MIA"}, {"game_id": "2", "home_team": "KC", "away_team": "LA"}]
    assert live.find_game_id(games, "BUF", "MIA") == "1"
    assert live.find_game_id(games, "MIA", "BUF") == "1"  # order-independent, same as odds.find_matchup


def test_find_game_id_no_match_returns_none():
    games = [{"game_id": "1", "home_team": "BUF", "away_team": "MIA"}]
    assert live.find_game_id(games, "KC", "LA") is None


def test_find_game_returns_full_entry_including_status():
    games = [{"game_id": "1", "home_team": "BUF", "away_team": "MIA", "status": "Final"}]
    game = live.find_game(games, "BUF", "MIA")
    assert game["status"] == "Final"
    assert game["game_id"] == "1"


def test_find_game_no_match_returns_none():
    assert live.find_game([{"game_id": "1", "home_team": "BUF", "away_team": "MIA"}], "KC", "LA") is None


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _injury_payload():
    return {
        "injuries": [
            {
                "team": {"abbreviation": "NYG"},
                "injuries": [
                    {
                        "status": "Out",
                        "athlete": {"fullName": "Jaxson Dart", "position": {"abbreviation": "QB"}},
                        "details": {"type": "Shoulder"},
                    }
                ],
            }
        ]
    }


def test_get_injuries_parses_real_shaped_payload(monkeypatch):
    monkeypatch.setattr(live._session, "get", lambda *a, **k: _FakeResponse(_injury_payload()))
    result = live.get_injuries("12345")
    assert set(result.keys()) == {"NYG"}
    df = result["NYG"]
    assert list(df.columns) == ["full_name", "position", "report_primary_injury", "report_status"]
    assert df.iloc[0]["full_name"] == "Jaxson Dart"
    assert df.iloc[0]["report_status"] == "Out"
    assert df.iloc[0]["report_primary_injury"] == "Shoulder"


def test_get_injuries_handles_missing_details(monkeypatch):
    payload = _injury_payload()
    payload["injuries"][0]["injuries"][0]["details"] = None
    monkeypatch.setattr(live._session, "get", lambda *a, **k: _FakeResponse(payload))
    result = live.get_injuries("12345")
    assert result["NYG"].iloc[0]["report_primary_injury"] is None


def test_get_injuries_applies_team_abbreviation_normalization(monkeypatch):
    payload = _injury_payload()
    payload["injuries"][0]["team"]["abbreviation"] = "LAR"
    monkeypatch.setattr(live._session, "get", lambda *a, **k: _FakeResponse(payload))
    result = live.get_injuries("12345")
    assert set(result.keys()) == {"LA"}  # LAR -> LA, same fix used by get_scoreboard/get_boxscore


def test_get_injuries_returns_empty_dict_on_network_failure(monkeypatch):
    def raise_error(*a, **k):
        raise live.requests.RequestException("boom")

    monkeypatch.setattr(live._session, "get", raise_error)
    assert live.get_injuries("12345") == {}


def test_get_injuries_returns_empty_dict_on_malformed_payload(monkeypatch):
    monkeypatch.setattr(live._session, "get", lambda *a, **k: _FakeResponse({"injuries": [{"team": {}}]}))
    assert live.get_injuries("12345") == {}


def test_get_injuries_batch_fetches_each_game_and_keys_by_id(monkeypatch):
    calls = []

    def fake_get_injuries(game_id):
        calls.append(game_id)
        return {"NYG": game_id}  # cheap stand-in, just needs to round-trip

    monkeypatch.setattr(live, "get_injuries", fake_get_injuries)
    result = live.get_injuries_batch(["111", "222", "333"])

    assert sorted(calls) == ["111", "222", "333"]  # every id fetched, order doesn't matter (concurrent)
    assert result == {"111": {"NYG": "111"}, "222": {"NYG": "222"}, "333": {"NYG": "333"}}


def test_get_injuries_batch_deduplicates_game_ids(monkeypatch):
    calls = []
    monkeypatch.setattr(live, "get_injuries", lambda game_id: calls.append(game_id) or {})
    live.get_injuries_batch(["111", "111", "222"])
    assert sorted(calls) == ["111", "222"]


def test_get_injuries_batch_empty_input_returns_empty_dict():
    assert live.get_injuries_batch([]) == {}
