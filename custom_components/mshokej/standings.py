from copy import deepcopy

GROUP_TEAMS = {
    "A": ["USA", "SUI", "FIN", "GER", "LAT", "AUT", "HUN", "GBR"],
    "B": ["CAN", "SWE", "CZE", "DEN", "SVK", "NOR", "SLO", "ITA"],
}

SEEDS = {
    "A": {"USA": 1, "SUI": 2, "FIN": 3, "GER": 4, "LAT": 5, "AUT": 6, "HUN": 7, "GBR": 8},
    "B": {"CAN": 1, "SWE": 2, "CZE": 3, "DEN": 4, "SVK": 5, "NOR": 6, "SLO": 7, "ITA": 8},
}

PROTECTED_RELEGATION_TEAMS = {"GER"}


def _is_played(match):
    return match.get("score_home") is not None and match.get("score_away") is not None and match.get("type") in {
        "REG",
        "OT",
        "SO",
        "LIVE",
    }


def _empty_stats(team):
    return {
        "team": team,
        "played": 0,
        "wins": 0,
        "otw": 0,
        "otl": 0,
        "losses": 0,
        "gf": 0,
        "ga": 0,
        "gd": 0,
        "points": 0,
    }


def _points_for_match(is_winner, result_type):
    if result_type == "REG":
        return 3 if is_winner else 0
    if result_type == "LIVE":
        return 3 if is_winner else 0
    return 2 if is_winner else 1


def _collect_group_matches(matches, group, only_played=True):
    out = []
    for match in matches:
        if match.get("phase") != "group" or match.get("group") != group:
            continue
        if only_played and not _is_played(match):
            continue
        out.append(match)
    return out


def _mini_table_metrics(team_codes, group_matches):
    stats = {team: {"points": 0, "gd": 0, "gf": 0} for team in team_codes}
    tied_set = set(team_codes)

    for match in group_matches:
        if not _is_played(match):
            continue
        home = match["home"]
        away = match["away"]
        if home not in tied_set or away not in tied_set:
            continue

        sh = match["score_home"]
        sa = match["score_away"]
        t = match["type"]

        stats[home]["gf"] += sh
        stats[home]["gd"] += sh - sa
        stats[away]["gf"] += sa
        stats[away]["gd"] += sa - sh

        if t == "LIVE":
            if sh == sa:
                stats[home]["points"] += 1
                stats[away]["points"] += 1
            elif sh > sa:
                stats[home]["points"] += 3
            else:
                stats[away]["points"] += 3
            continue

        if sh > sa:
            stats[home]["points"] += _points_for_match(True, t)
            stats[away]["points"] += _points_for_match(False, t)
        elif sa > sh:
            stats[home]["points"] += _points_for_match(False, t)
            stats[away]["points"] += _points_for_match(True, t)
        else:
            stats[home]["points"] += _points_for_match(False, t)
            stats[away]["points"] += _points_for_match(False, t)

    return stats


def _result_against(team, opponent, group_matches):
    for match in group_matches:
        if not _is_played(match):
            continue
        home = match["home"]
        away = match["away"]
        if {home, away} != {team, opponent}:
            continue

        sh = match["score_home"]
        sa = match["score_away"]
        t = match["type"]

        if team == home:
            gf = sh
            ga = sa
            won = sh > sa
        else:
            gf = sa
            ga = sh
            won = sa > sh

        if t == "LIVE" and gf == ga:
            pts = 1
        else:
            pts = _points_for_match(won, t)
        return (pts, gf - ga, gf)

    return (-1, -999, -999)


def _rank_tied_recursive(team_codes, group_matches, group, higher_ranked, overall_rows):
    if len(team_codes) <= 1:
        return team_codes

    mini = _mini_table_metrics(team_codes, group_matches)
    seed_map = SEEDS[group]

    def resolve_current(codes, criterion):
        if len(codes) <= 1:
            return codes
        if criterion > 10:
            return sorted(codes, key=lambda x: seed_map[x])

        if criterion == 2:
            metric = {c: mini[c]["points"] for c in codes}
            reverse = True
        elif criterion == 3:
            metric = {c: mini[c]["gd"] for c in codes}
            reverse = True
        elif criterion == 4:
            metric = {c: mini[c]["gf"] for c in codes}
            reverse = True
        elif criterion == 5:
            if not higher_ranked:
                return resolve_current(codes, 6)
            opponent = higher_ranked[-1]
            metric = {c: _result_against(c, opponent, group_matches) for c in codes}
            reverse = True
        elif criterion == 6:
            if len(higher_ranked) < 2:
                return resolve_current(codes, 7)
            opponent = higher_ranked[-2]
            metric = {c: _result_against(c, opponent, group_matches) for c in codes}
            reverse = True
        elif criterion == 7:
            metric = {c: overall_rows[c]["gd"] for c in codes}
            reverse = True
        elif criterion == 8:
            metric = {c: overall_rows[c]["gf"] for c in codes}
            reverse = True
        elif criterion == 9:
            metric = {c: overall_rows[c]["played"] for c in codes}
            reverse = False  # Mene odehranych zapasu je lepsi
        else:
            metric = {c: -seed_map[c] for c in codes}
            reverse = True

        buckets = {}
        for c in codes:
            buckets.setdefault(metric[c], []).append(c)

        ordered_keys = sorted(buckets.keys(), reverse=reverse)
        resolved = []
        resolved_so_far = []

        for key in ordered_keys:
            subgroup = buckets[key]
            if len(subgroup) == 1:
                resolved.append(subgroup[0])
                resolved_so_far.append(subgroup[0])
                continue

            sub_higher = higher_ranked + resolved_so_far
            sub_resolved = resolve_current(subgroup, criterion + 1)
            resolved.extend(sub_resolved)
            resolved_so_far.extend(sub_resolved)

        return resolved

    return resolve_current(list(team_codes), 2)


def tiebreak(teams, all_matches):
    if not teams:
        return []
    group = teams[0]["group"]
    group_matches = _collect_group_matches(all_matches, group, only_played=True)

    points_buckets = {}
    for row in teams:
        points_buckets.setdefault(row["points"], []).append(row["team"])

    ordered_points = sorted(points_buckets.keys(), reverse=True)
    final_order = []

    for pts in ordered_points:
        tied = points_buckets[pts]
        if len(tied) == 1:
            final_order.extend(tied)
        else:
            # Nejdrive vyhodnotit podle sportovnich kriterii (GD, GF, h2h...)
            overall_rows = {row["team"]: row for row in teams}
            sport_ranked = _rank_tied_recursive(tied, group_matches, group, final_order.copy(), overall_rows)

            # Pokud je po sportovnich kriteriich stale remiza, rozhoduje pocet odehranych zapasu
            played_buckets = {}
            for team_code in sport_ranked:
                played = next(row["played"] for row in teams if row["team"] == team_code)
                played_buckets.setdefault(played, []).append(team_code)

            for played_count in sorted(played_buckets.keys()):
                final_order.extend(played_buckets[played_count])

    team_to_row = {row["team"]: row for row in teams}
    out = []
    for code in final_order:
        item = deepcopy(team_to_row[code])
        item.pop("group", None)
        out.append(item)
    return out


def calculate_standings(matches, group):
    teams = GROUP_TEAMS[group]
    stats = {team: _empty_stats(team) for team in teams}

    for match in _collect_group_matches(matches, group, only_played=True):
        home = match["home"]
        away = match["away"]
        sh = match["score_home"]
        sa = match["score_away"]
        result_type = match["type"]

        stats[home]["played"] += 1
        stats[away]["played"] += 1

        stats[home]["gf"] += sh
        stats[home]["ga"] += sa
        stats[away]["gf"] += sa
        stats[away]["ga"] += sh

        if result_type == "LIVE":
            # LIVE zapas se boduje podle aktualniho skore
            if sh == sa:
                stats[home]["points"] += 1
                stats[away]["points"] += 1
            elif sh > sa:
                stats[home]["points"] += 3
            else:
                stats[away]["points"] += 3
            continue

        if sh > sa:
            winner = home
            loser = away
            if result_type == "REG":
                stats[winner]["wins"] += 1
                stats[loser]["losses"] += 1
            else:
                stats[winner]["otw"] += 1
                stats[loser]["otl"] += 1

            stats[winner]["points"] += _points_for_match(True, result_type)
            stats[loser]["points"] += _points_for_match(False, result_type)
        elif sa > sh:
            winner = away
            loser = home
            if result_type == "REG":
                stats[winner]["wins"] += 1
                stats[loser]["losses"] += 1
            else:
                stats[winner]["otw"] += 1
                stats[loser]["otl"] += 1

            stats[winner]["points"] += _points_for_match(True, result_type)
            stats[loser]["points"] += _points_for_match(False, result_type)
        else:
            # Tato vettev je bezna jen pro LIVE, ktere je zpracovane vyse.
            continue

    rows = []
    for team in teams:
        row = deepcopy(stats[team])
        row["gd"] = row["gf"] - row["ga"]
        row["group"] = group
        rows.append(row)

    return tiebreak(rows, matches)


def _annotated_group_rows(standings, group):
    annotated = []
    for idx, row in enumerate(standings, start=1):
        item = deepcopy(row)
        item["group"] = group
        item["group_position"] = idx
        item["seed"] = SEEDS[group][row["team"]]
        item["points"] = item.get("points", 0)
        item["gd"] = item.get("gd", 0)
        item["gf"] = item.get("gf", 0)
        annotated.append(item)
    return annotated


def _preliminary_round_sort_key(row):
    return (row["group_position"], -row["points"], -row["gd"], -row["gf"], row["seed"])


def rank_teams_by_preliminary_round(standings_a, standings_b, team_codes=None, positions=None):
    rows = _annotated_group_rows(standings_a, "A") + _annotated_group_rows(standings_b, "B")
    if team_codes is not None:
        allowed = set(team_codes)
        rows = [row for row in rows if row["team"] in allowed]
    if positions is not None:
        allowed_positions = set(positions)
        rows = [row for row in rows if row["group_position"] in allowed_positions]
    return sorted(rows, key=_preliminary_round_sort_key)


def relegated_teams(standings_a, standings_b, protected_teams=None):
    protected = PROTECTED_RELEGATION_TEAMS if protected_teams is None else set(protected_teams)
    ranked = rank_teams_by_preliminary_round(standings_a, standings_b, positions={5, 6, 7, 8})
    relegated = []
    for row in reversed(ranked):
        if row["team"] in protected:
            continue
        relegated.append(row["team"])
        if len(relegated) == 2:
            break
    return relegated
