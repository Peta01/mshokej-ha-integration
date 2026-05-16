from datetime import datetime


def normalize_date(date_str):
    if not date_str or date_str == "unknown":
        return None

    if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
        return date_str

    try:
        if "." in date_str:
            parts = date_str.split(".")
            day = parts[0].strip()
            month = parts[1].strip()
            year = parts[2].strip() if len(parts) > 2 else str(datetime.now().year)
            if len(year) == 1 or len(year) == 2:
                year = "202" + year if len(year) == 1 else "20" + year
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    except (IndexError, ValueError):
        return None

    return None


def normalize_time(time_str):
    if not time_str or time_str == "unknown":
        return None
    if len(time_str) == 5 and time_str[2] == ":":
        return time_str
    return None


def find_match_index(results, home, away, date, time):
    for idx, match in enumerate(results.get("matches", [])):
        if (
            match.get("home") == home
            and match.get("away") == away
            and match.get("date") == date
            and match.get("time") == time
        ):
            return idx

    team_candidates = [
        idx
        for idx, match in enumerate(results.get("matches", []))
        if match.get("home") == home and match.get("away") == away
    ]
    if len(team_candidates) == 1:
        return team_candidates[0]

    return -1


def should_update_match(match, score_home, score_away, match_type, live_period, live_clock, live_status):
    return (
        match.get("score_home") != score_home
        or match.get("score_away") != score_away
        or match.get("type") != match_type
        or match.get("live_period") != live_period
        or match.get("live_clock") != live_clock
        or match.get("live_status") != live_status
    )


def should_clear_stale_live(match, feed_live_keys):
    if match.get("type") != "LIVE":
        return False

    key = (match.get("home"), match.get("away"), match.get("date"), match.get("time"))
    return key not in feed_live_keys


def update_results_dataset(results, livesport_data, today=None):
    working = {"matches": [dict(match) for match in results.get("matches", [])]}
    current_day = today or datetime.now().strftime("%Y-%m-%d")
    updated_count = 0
    updated_matches = []
    warnings = []
    feed_live_keys = set()

    for livesport_match in livesport_data:
        home = livesport_match.get("home")
        away = livesport_match.get("away")
        score_home = livesport_match.get("score_home")
        score_away = livesport_match.get("score_away")
        match_type = livesport_match.get("type", "REG")
        live_period = livesport_match.get("live_period")
        live_clock = livesport_match.get("live_clock")
        live_status = livesport_match.get("live_status")
        date = normalize_date(livesport_match.get("date"))
        time = normalize_time(livesport_match.get("time"))

        if not date or not time:
            warnings.append(f"Zapas {home} vs {away}: nelze parsovat datum/cas")
            continue

        match_index = find_match_index(working, home, away, date, time)
        if match_index == -1:
            warnings.append(f"Zapas {home} vs {away} ({date} {time}): nenalezen v results")
            continue

        match = working["matches"][match_index]
        match_id = match.get("id", "unknown")
        if match_type == "LIVE":
            feed_live_keys.add((match.get("home"), match.get("away"), match.get("date"), match.get("time")))
        if should_update_match(match, score_home, score_away, match_type, live_period, live_clock, live_status):
            match["score_home"] = score_home
            match["score_away"] = score_away
            match["type"] = match_type
            if match_type == "LIVE":
                match["live_period"] = live_period
                if live_clock:
                    match["live_clock"] = live_clock
                else:
                    match.pop("live_clock", None)
                if live_status:
                    match["live_status"] = live_status
                else:
                    match.pop("live_status", None)
            else:
                match.pop("live_period", None)
                match.pop("live_clock", None)
                match.pop("live_status", None)

            updated_count += 1
            updated_matches.append(match_id)

    for match in working.get("matches", []):
        if not should_clear_stale_live(match, feed_live_keys):
            continue

        match["score_home"] = None
        match["score_away"] = None
        match["type"] = None
        match.pop("live_period", None)
        match.pop("live_clock", None)
        match.pop("live_status", None)
        updated_count += 1
        updated_matches.append(match.get("id", "unknown"))

    return {
        "results": working,
        "updated_count": updated_count,
        "updated_matches": updated_matches,
        "warnings": warnings,
        "success": updated_count > 0 or len(warnings) == 0,
        "today": current_day,
    }
