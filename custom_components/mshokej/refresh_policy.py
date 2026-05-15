from datetime import datetime, timedelta
from math import ceil


DEFAULT_LIVE_POLL_INTERVAL = 60
DEFAULT_PRE_MATCH_BUFFER = 60
DEFAULT_IDLE_POLL_INTERVAL = 3600


def has_live_matches(matches):
    return any(match.get("type") == "LIVE" for match in matches)


def next_match_start(matches, now=None):
    current = now or datetime.now()
    upcoming = []

    for match in matches:
        if match.get("score_home") is not None and match.get("score_away") is not None:
            continue

        date_str = match.get("date") or ""
        time_str = match.get("time") or "00:00"
        try:
            start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue

        if start > current:
            upcoming.append(start)

    return min(upcoming) if upcoming else None


def compute_refresh_plan(
    matches,
    now=None,
    live_poll_interval=DEFAULT_LIVE_POLL_INTERVAL,
    pre_match_buffer=DEFAULT_PRE_MATCH_BUFFER,
    idle_poll_interval=DEFAULT_IDLE_POLL_INTERVAL,
):
    current = now or datetime.now()
    next_start = next_match_start(matches, current)

    if has_live_matches(matches):
        next_refresh_at = current + timedelta(seconds=live_poll_interval)
        return {
            "mode": "live",
            "seconds": live_poll_interval,
            "next_match_start": next_start,
            "next_refresh_at": next_refresh_at,
        }

    if next_start is None:
        next_refresh_at = current + timedelta(seconds=idle_poll_interval)
        return {
            "mode": "idle",
            "seconds": idle_poll_interval,
            "next_match_start": None,
            "next_refresh_at": next_refresh_at,
        }

    wake_at = next_start - timedelta(seconds=pre_match_buffer)
    if wake_at <= current:
        return {
            "mode": "pre-match",
            "seconds": 1,
            "next_match_start": next_start,
            "next_refresh_at": current + timedelta(seconds=1),
        }

    wait_seconds = ceil((wake_at - current).total_seconds())
    return {
        "mode": "scheduled",
        "seconds": wait_seconds,
        "next_match_start": next_start,
        "next_refresh_at": wake_at,
    }
