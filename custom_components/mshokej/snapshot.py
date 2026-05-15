from datetime import datetime

from .bracket import generate_bracket, sync_playoff_matches
from .predict import predict_advancement
from .standings import GROUP_TEAMS, calculate_standings, relegated_teams


PHASE_LABELS = {
    "group": "Skupina",
    "QF": "Čtvrtfinále",
    "SF": "Semifinále",
    "bronze": "O 3. místo",
    "final": "Finále",
}

PERIOD_MAP = {
    "1T": "1. třetina",
    "2T": "2. třetina",
    "3T": "3. třetina",
    "1. tretina": "1. třetina",
    "2. tretina": "2. třetina",
    "3. tretina": "3. třetina",
    "1. t?etina": "1. třetina",
    "2. t?etina": "2. třetina",
    "3. t?etina": "3. třetina",
    "1. třetina": "1. třetina",
    "2. třetina": "2. třetina",
    "3. třetina": "3. třetina",
}


def _is_played(match):
    return match.get("score_home") is not None and match.get("score_away") is not None and match.get("type")


def _result_parts(match):
    if not _is_played(match):
        return {"text": "vs", "suffix": None, "live_phase": None, "live_sub": None, "type": None}

    text = f"{match['score_home']}:{match['score_away']}"
    suffix = None
    live_phase = None
    live_sub = None
    result_type = match.get("type")

    if result_type in {"OT", "SO"}:
        suffix = result_type
    elif result_type == "LIVE":
        period_raw = (match.get("live_period") or "").strip()
        live_phase = PERIOD_MAP.get(period_raw, period_raw or "LIVE")
        live_clock = (match.get("live_clock") or "").strip()
        live_status = (match.get("live_status") or "").strip()
        live_sub = live_clock or live_status or None

    return {
        "text": text,
        "suffix": suffix,
        "live_phase": live_phase,
        "live_sub": live_sub,
        "type": result_type,
    }


def _serialize_match(match, today, favorite_team):
    return {
        "id": match["id"],
        "date": match["date"],
        "time": match["time"],
        "venue": match["venue"],
        "phase": match.get("phase"),
        "phase_label": PHASE_LABELS.get(match.get("phase"), match.get("phase") or "-"),
        "group": match.get("group"),
        "group_label": match.get("group") or "-",
        "home": match["home"],
        "away": match["away"],
        "is_today": match["date"] == today,
        "is_favorite_match": favorite_team in {match.get("home"), match.get("away")},
        "is_played": _is_played(match),
        "result": _result_parts(match),
    }


def _serialize_table_rows(rows, relegated, favorite_team):
    output = []
    for idx, row in enumerate(rows, start=1):
        output.append(
            {
                "position": idx,
                "team": row["team"],
                "played": row["played"],
                "wins": row["wins"],
                "otw": row["otw"],
                "otl": row["otl"],
                "losses": row["losses"],
                "gf": row["gf"],
                "ga": row["ga"],
                "gd": row["gd"],
                "points": row["points"],
                "is_top4": idx <= 4,
                "is_relegated": row["team"] in relegated,
                "is_favorite_team": row["team"] == favorite_team,
            }
        )
    return output


def _serialize_bracket_match(match_id, pair, by_id, today, favorite_team):
    match = by_id.get(match_id, {"id": match_id, "date": "", "time": "", "venue": "", "phase": None, "group": None, "home": pair[0], "away": pair[1]})
    data = _serialize_match(match, today, favorite_team)
    data["pair"] = {"home": pair[0], "away": pair[1]}
    data["is_final"] = match_id == "FIN"
    data["is_bronze"] = match_id == "BRO"
    return data


def _with_diacritics(text):
    replacements = [
        ("postupova", "postupová"),
        ("sance", "šance"),
        ("zije", "žije"),
        ("presny", "přesný"),
        ("vypocet", "výpočet"),
        ("zatim", "zatím"),
        ("neni", "není"),
        ("dostupny", "dostupný"),
        ("vsech", "všech"),
        ("zbyvajicich", "zbývajících"),
        ("kombinacich", "kombinacích"),
        ("zustava", "zůstává"),
        ("konecne", "konečně"),
        ("nema", "nemá"),
        ("zadnou", "žádnou"),
        ("vedouci", "vedoucí"),
        ("vychazi", "vychází"),
        ("misto", "místo"),
    ]
    for source, target in replacements:
        text = text.replace(source, target)
    return text


def _serialize_predictions(matches):
    predictions = []
    for group in ["A", "B"]:
        for team in GROUP_TEAMS[group]:
            has_unplayed = any(
                match["phase"] == "group"
                and match["group"] == group
                and team in {match["home"], match["away"]}
                and (match["score_home"] is None or match["score_away"] is None)
                for match in matches
            )
            if not has_unplayed:
                continue

            text = predict_advancement(team, matches)
            if "Už nemá reálnou kombinaci" in text:
                continue
            summary = text.splitlines()[1] if len(text.splitlines()) > 1 else text
            predictions.append({"team": team, "summary": _with_diacritics(summary.strip("- ").strip())})
    return predictions


def build_snapshot(
    matches,
    title="Mistrovství světa v ledním hokeji 2026",
    favorite_team="CZE",
    generated_at=None,
    refresh_mode=None,
    refresh_interval_seconds=None,
    next_refresh_at=None,
):
    working_matches = [dict(match) for match in matches]
    standings_a = calculate_standings(working_matches, "A")
    standings_b = calculate_standings(working_matches, "B")
    relegated = set(relegated_teams(standings_a, standings_b))
    sync_playoff_matches(working_matches, standings_a, standings_b)
    bracket = generate_bracket(working_matches, standings_a, standings_b)
    by_id = {match["id"]: match for match in working_matches}

    now = generated_at or datetime.now()
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    ordered = sorted(working_matches, key=lambda match: (match["date"], match["time"], match["id"]))
    played = [_serialize_match(match, today, favorite_team) for match in ordered if _is_played(match)]
    remaining = [_serialize_match(match, today, favorite_team) for match in ordered if not _is_played(match)]
    nearest = remaining[:8]

    next_match = remaining[0] if remaining else None

    return {
        "title": title,
        "favorite_team": favorite_team,
        "meta": {
            "generated_at": now_iso,
            "last_update_label": now.strftime("%Y-%m-%d %H:%M:%S"),
            "refresh_mode": refresh_mode,
            "refresh_interval_seconds": refresh_interval_seconds,
            "next_refresh_at": next_refresh_at.isoformat() if next_refresh_at else None,
        },
        "overview": {
            "played": len(played),
            "total": len(working_matches),
            "remaining": len(working_matches) - len(played),
            "group_total": sum(1 for match in working_matches if match.get("phase") == "group"),
            "group_played": sum(1 for match in working_matches if match.get("phase") == "group" and _is_played(match)),
        },
        "groups": {
            "A": _serialize_table_rows(standings_a, relegated, favorite_team),
            "B": _serialize_table_rows(standings_b, relegated, favorite_team),
        },
        "bracket": {
            "QF": [_serialize_bracket_match(match_id, bracket["QF"][match_id], by_id, today, favorite_team) for match_id in ["QF1", "QF2", "QF3", "QF4"]],
            "SF": [_serialize_bracket_match(match_id, bracket["SF"][match_id], by_id, today, favorite_team) for match_id in ["SF1", "SF2"]],
            "MEDAL": [
                _serialize_bracket_match("BRO", bracket["BRO"], by_id, today, favorite_team),
                _serialize_bracket_match("FIN", bracket["FIN"], by_id, today, favorite_team),
            ],
        },
        "sections": {
            "nearest": nearest,
            "played": played,
            "remaining": remaining,
        },
        "predictions": _serialize_predictions(working_matches),
        "relegated": sorted(relegated),
        "next_match": next_match,
    }
