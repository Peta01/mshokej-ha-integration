from copy import deepcopy
from itertools import product

from .standings import GROUP_TEAMS, calculate_standings


MAX_DIRECT_COMBINATIONS_MATCHES = 7


def _find_group(team):
    for group, teams in GROUP_TEAMS.items():
        if team in teams:
            return group
    return None


def _is_unplayed_group_match(match, group):
    return (
        match.get("phase") == "group"
        and match.get("group") == group
        and (match.get("score_home") is None or match.get("score_away") is None)
    )


def _apply_combo(base_matches, pending, combo):
    updated = deepcopy(base_matches)
    by_id = {m["id"]: m for m in updated}
    for match, home_win in zip(pending, combo):
        current = by_id[match["id"]]
        if home_win:
            current["score_home"] = 1
            current["score_away"] = 0
        else:
            current["score_home"] = 0
            current["score_away"] = 1
        current["type"] = "REG"
    return updated


def _team_rank(st, team):
    for idx, row in enumerate(st, start=1):
        if row["team"] == team:
            return idx
    return 999


def _current_group_snapshot(team, matches, standings=None):
    group = _find_group(team)
    if group is None:
        return None

    st = standings if standings is not None else calculate_standings(matches, group)
    row = next((item for item in st if item["team"] == team), None)
    if row is None:
        return None

    pending = [m for m in matches if _is_unplayed_group_match(m, group)]
    pending_for_team = [m for m in pending if team in {m["home"], m["away"]}]

    return {
        "group": group,
        "standings": st,
        "row": row,
        "rank": _team_rank(st, team),
        "pending": pending,
        "pending_for_team": pending_for_team,
    }


def _format_opponents(pending_for_team, team):
    opponents = [m["away"] if m["home"] == team else m["home"] for m in pending_for_team]
    if not opponents:
        return "zadny"
    return ", ".join(opponents)


def _lines_with_context(team, snapshot, verdict):
    current_points = snapshot["row"]["points"]
    pending_for_team = snapshot["pending_for_team"]
    max_points = current_points + 3 * len(pending_for_team)

    return [
        f"{team} - predikce postupu:",
        verdict,
        (
            f"  - Aktualne: {snapshot['rank']}. misto, {current_points} b.; "
            f"zbyva {len(pending_for_team)} zapasu ({_format_opponents(pending_for_team, team)})."
        ),
        f"  - Bodove rozpati: {current_points}-{max_points} b.",
    ]


def _possible_points_by_team(snapshot):
    pending_counts = {team: 0 for team in GROUP_TEAMS[snapshot["group"]]}
    for match in snapshot["pending"]:
        pending_counts[match["home"]] += 1
        pending_counts[match["away"]] += 1

    out = {}
    for row in snapshot["standings"]:
        team = row["team"]
        current_points = row["points"]
        out[team] = {
            "current": current_points,
            "min": current_points,
            "max": current_points + 3 * pending_counts[team],
        }
    return out


def _theoretical_rank_bounds(team, points_by_team):
    target = points_by_team[team]
    best_rank = 1 + sum(1 for other, pts in points_by_team.items() if other != team and pts["min"] > target["max"])
    worst_rank = 1 + sum(1 for other, pts in points_by_team.items() if other != team and pts["max"] >= target["min"])
    return best_rank, worst_rank


def _fallback_prediction_lines(team, snapshot):
    points_by_team = _possible_points_by_team(snapshot)
    target = points_by_team[team]
    best_rank, worst_rank = _theoretical_rank_bounds(team, points_by_team)

    forced_above = sum(1 for other, pts in points_by_team.items() if other != team and pts["min"] > target["max"])
    locked_behind = sum(1 for other, pts in points_by_team.items() if other != team and pts["max"] < target["min"])

    if forced_above >= 4:
        verdict = f"  - Verdikt: ani maximum {target['max']} b. uz nestaci na top 4."
    elif locked_behind >= 4:
        verdict = "  - Verdikt: uz ma jistotu postupu do top 4."
    else:
        verdict = "  - Verdikt: postupova sance zije, ale presny vypocet zatim neni dostupny."

    fourth_points = snapshot["standings"][3]["points"]
    leader_points = snapshot["standings"][0]["points"]

    lines = _lines_with_context(team, snapshot, verdict)
    lines.append(f"  - Teoreticke meze umisteni: nejlepe {best_rank}., nejhure {worst_rank}. misto.")
    lines.append(f"  - Pro orientaci: 4. misto ma ted {fourth_points} b., lider ma {leader_points} b.")
    lines.append(
        f"  - Primy vypocet se zapne pozdeji: ve skupine {snapshot['group']} je jeste "
        f"{len(snapshot['pending'])} neodehranych zapasu, limit je {MAX_DIRECT_COMBINATIONS_MATCHES}."
    )
    return lines


def predict_advancement(team, matches, _standings=None):
    snapshot = _current_group_snapshot(team, matches, _standings)
    if snapshot is None:
        return f"Tým {team} není platná zkratka účastníka MS 2026."

    pending = snapshot["pending"]
    pending_for_team = snapshot["pending_for_team"]

    if len(pending) == 0:
        rank = snapshot["rank"]
        if rank <= 4:
            lines = _lines_with_context(team, snapshot, f"  - Verdikt: konecne postoupil z {rank}. mista.")
        else:
            lines = _lines_with_context(team, snapshot, f"  - Verdikt: konecne nepostoupil ({rank}. misto).")
        lines.append("  - Tym uz nema zadne zbyvajici skupinove zapasy.")
        if rank <= 4:
            return "\n".join(lines)
        return "\n".join(lines)

    if len(pending) > MAX_DIRECT_COMBINATIONS_MATCHES:
        return "\n".join(_fallback_prediction_lines(team, snapshot))

    outcomes = []
    for combo in product([False, True], repeat=len(pending)):
        simulated = _apply_combo(matches, pending, combo)
        st = calculate_standings(simulated, snapshot["group"])
        rank = _team_rank(st, team)
        top4 = rank <= 4

        own_wins = 0
        own_total = len(pending_for_team)
        own_detail = []

        for m, home_win in zip(pending, combo):
            if team not in {m["home"], m["away"]}:
                continue
            team_won = (m["home"] == team and home_win) or (m["away"] == team and not home_win)
            own_wins += 1 if team_won else 0
            opp = m["away"] if m["home"] == team else m["home"]
            own_detail.append((opp, team_won))

        outcomes.append(
            {
                "top4": top4,
                "rank": rank,
                "own_wins": own_wins,
                "own_total": own_total,
                "own_detail": own_detail,
            }
        )

    success = [o for o in outcomes if o["top4"]]
    fail = [o for o in outcomes if not o["top4"]]

    if len(success) == len(outcomes):
        lines = _lines_with_context(team, snapshot, "  - Verdikt: pri vsech zbyvajicich kombinacich zustava v top 4.")
        lines.append(f"  - Presny rozsah umisteni: {min(o['rank'] for o in outcomes)}.-{max(o['rank'] for o in outcomes)}. misto.")
        return "\n".join(lines)

    if len(success) == 0:
        lines = _lines_with_context(team, snapshot, "  - Verdikt: uz nema zadnou kombinaci vedouci do top 4.")
        lines.append(f"  - Presny rozsah umisteni: {min(o['rank'] for o in outcomes)}.-{max(o['rank'] for o in outcomes)}. misto.")
        return "\n".join(lines)

    lines = _lines_with_context(
        team,
        snapshot,
        f"  - Verdikt: postup vychazi v {len(success)} z {len(outcomes)} kombinaci ({len(success) * 100 // len(outcomes)} %).",
    )

    max_own = max(o["own_wins"] for o in success)
    min_own_success = min(o["own_wins"] for o in success)
    max_own_fail = max(o["own_wins"] for o in fail)
    best_rank = min(o["rank"] for o in outcomes)
    worst_rank = max(o["rank"] for o in outcomes)

    lines.append(f"  - Presny rozsah umisteni: {best_rank}.-{worst_rank}. misto.")

    if len(pending_for_team) == 0:
        lines.append("  - Tym uz ma odehrano vse; rozhodnou jen vysledky ostatnich.")
        return "\n".join(lines)

    if min_own_success > max_own_fail:
        lines.append(
            f"  - Postup si umi zajistit pri alespon {min_own_success} vyhrach z {success[0]['own_total']} zbyvajicich zapasu."
        )
    else:
        lines.append(
            "  - Samotny pocet vlastnich vyher nestaci; rozhodnou i vysledky ostatnich tymu."
        )

    for m in pending_for_team:
        opp = m["away"] if m["home"] == team else m["home"]
        succ_when_win = []
        succ_when_lose = []
        for out in outcomes:
            for d_opp, d_won in out["own_detail"]:
                if d_opp != opp:
                    continue
                if d_won:
                    succ_when_win.append(out["top4"])
                else:
                    succ_when_lose.append(out["top4"])

        if succ_when_win and all(succ_when_win):
            lines.append(f"  - Vyhra nad {opp} udrzi postupovou sanci ve vsech dalsich scenarich.")
        if succ_when_lose and not any(succ_when_lose):
            lines.append(f"  - Prohra s {opp} okamzite zavira vsechny postupove scenare.")

    lines.append(f"  - Nejlepsi varianta mezi uspesnymi scenari: {max_own} vlastnich vyher v zaveru.")

    return "\n".join(lines)


def predict_all(matches):
    out = []
    for group in ["A", "B"]:
        for team in GROUP_TEAMS[group]:
            out.append(predict_advancement(team, matches))
    return "\n\n".join(out)
