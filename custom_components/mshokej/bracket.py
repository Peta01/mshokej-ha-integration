from .standings import rank_teams_by_preliminary_round


def _is_played(match):
    return match.get("score_home") is not None and match.get("score_away") is not None and match.get("type") in {
        "REG",
        "OT",
        "SO",
    }


def _winner(match):
    if not _is_played(match):
        return None
    if match["score_home"] > match["score_away"]:
        return match["home"]
    return match["away"]


def _loser(match):
    if not _is_played(match):
        return None
    if match["score_home"] > match["score_away"]:
        return match["away"]
    return match["home"]


def _has_any_group_result(matches):
    return any(match.get("phase") == "group" and _is_played(match) for match in matches)


def quarterfinal_placeholders():
    return {
        "QF1": ("TBD", "TBD"),
        "QF2": ("TBD", "TBD"),
        "QF3": ("TBD", "TBD"),
        "QF4": ("TBD", "TBD"),
    }


def semifinal_placeholders():
    return {
        "SF1": ("TBD", "TBD"),
        "SF2": ("TBD", "TBD"),
    }


def quarterfinal_pairs(standings_a, standings_b):
    return {
        "QF1": (standings_a[0]["team"], standings_b[3]["team"]),
        "QF2": (standings_a[1]["team"], standings_b[2]["team"]),
        "QF3": (standings_b[0]["team"], standings_a[3]["team"]),
        "QF4": (standings_b[1]["team"], standings_a[2]["team"]),
    }


def semifinal_pairs(standings_a, standings_b, semifinalists):
    ranked = rank_teams_by_preliminary_round(standings_a, standings_b, team_codes=semifinalists)
    if len(ranked) != 4:
        return semifinal_placeholders()

    pair_high_low = (ranked[0]["team"], ranked[3]["team"])
    pair_mid = (ranked[1]["team"], ranked[2]["team"])

    if "SUI" in pair_mid and "SUI" not in pair_high_low:
        return {"SF1": pair_mid, "SF2": pair_high_low}
    return {"SF1": pair_high_low, "SF2": pair_mid}


def _sync_match_pairs(matches, desired_pairs):
    by_id = {match["id"]: match for match in matches}
    changed = False

    for match_id, (home, away) in desired_pairs.items():
        match = by_id.get(match_id)
        if not match or _is_played(match):
            continue
        if match.get("home") != home or match.get("away") != away:
            match["home"] = home
            match["away"] = away
            changed = True

    return changed


def sync_quarterfinal_matches(matches, standings_a=None, standings_b=None):
    if _has_any_group_result(matches):
        if standings_a is None or standings_b is None:
            from .standings import calculate_standings

            standings_a = calculate_standings(matches, "A")
            standings_b = calculate_standings(matches, "B")

        desired_pairs = quarterfinal_pairs(standings_a, standings_b)
    else:
        desired_pairs = quarterfinal_placeholders()

    return _sync_match_pairs(matches, desired_pairs)


def sync_playoff_matches(matches, standings_a=None, standings_b=None):
    changed = sync_quarterfinal_matches(matches, standings_a, standings_b)
    if standings_a is None or standings_b is None:
        from .standings import calculate_standings

        standings_a = calculate_standings(matches, "A")
        standings_b = calculate_standings(matches, "B")

    by_id = {match["id"]: match for match in matches}
    semifinalists = [_winner(by_id.get(qf_id, {})) for qf_id in ["QF1", "QF2", "QF3", "QF4"]]
    desired_semifinals = semifinal_placeholders()
    if all(semifinalists):
        desired_semifinals = semifinal_pairs(standings_a, standings_b, semifinalists)

    changed = _sync_match_pairs(
        matches,
        desired_semifinals,
    ) or changed

    by_id = {match["id"]: match for match in matches}
    changed = _sync_match_pairs(
        matches,
        {
            "BRO": (_loser(by_id.get("SF1", {})) or "TBD", _loser(by_id.get("SF2", {})) or "TBD"),
            "FIN": (_winner(by_id.get("SF1", {})) or "TBD", _winner(by_id.get("SF2", {})) or "TBD"),
        },
    ) or changed

    return changed


def generate_bracket(matches, standings_a, standings_b):
    by_id = {m["id"]: m for m in matches}
    qf_home_away = quarterfinal_pairs(standings_a, standings_b)

    semifinalists = [_winner(by_id.get(qf_id, {})) for qf_id in ["QF1", "QF2", "QF3", "QF4"]]
    sf_map = semifinal_placeholders()
    if all(semifinalists):
        sf_map = semifinal_pairs(standings_a, standings_b, semifinalists)

    sf_winners = {}
    sf_losers = {}
    for sf_id in ["SF1", "SF2"]:
        sf_match = by_id.get(sf_id, {})
        sf_winners[sf_id] = _winner(sf_match)
        sf_losers[sf_id] = _loser(sf_match)

    bronze_pair = (sf_losers.get("SF1") or "LSF1", sf_losers.get("SF2") or "LSF2")
    final_pair = (sf_winners.get("SF1") or "WSF1", sf_winners.get("SF2") or "WSF2")

    return {
        "QF": qf_home_away,
        "SF": sf_map,
        "BRO": bronze_pair,
        "FIN": final_pair,
    }
