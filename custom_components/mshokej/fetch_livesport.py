#!/usr/bin/env python3
"""
Web scraping skript pro stazeni vysledku zapasu z livesport.cz
Vraci JSON se seznamem zapasu s vysledky.
"""

import json
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional

import requests

URL = "https://www.livesport.cz/hokej/svet/mistrovstvi-sveta/live-tabulka/"
RESULTS_URL = "https://www.livesport.cz/hokej/svet/mistrovstvi-sveta/vysledky/"

TEAM_MAPPING = {
    "kanada": "CAN",
    "finsko": "FIN", "finska": "FIN", "finsland": "FIN",
    "nemecko": "GER", "německo": "GER", "německá": "GER", "nemecka": "GER", "germania": "GER",
    "usa": "USA", "spojene staty": "USA",
    "švýcarsko": "SUI", "schweiz": "SUI", "svycarsko": "SUI", "svajciarsko": "SUI",
    "britannie": "GBR", "británie": "GBR", "velká británie": "GBR", "anglie": "GBR",
    "velka britanie": "GBR", "velika britanie": "GBR", "velika britanija": "GBR",
    "rakousko": "AUT", "rakouska": "AUT", "rakousku": "AUT",
    "maďarsko": "HUN", "madarsko": "HUN", "madarsku": "HUN", "madarská": "HUN",
    "lotyšsko": "LAT", "lotyssko": "LAT", "lotyska": "LAT", "lettonie": "LAT",
    "francie": "FRA", "francusko": "FRA", "francouzska": "FRA", "francouzsku": "FRA",
    "itálie": "ITA", "italie": "ITA", "italisansko": "ITA", "italien": "ITA",
    "dánsko": "DEN", "dansko": "DEN", "dansku": "DEN", "danmark": "DEN",
    "slovinsko": "SLO", "slovinska": "SLO", "slovenija": "SLO", "slovenija": "SLO",
    "slovensko": "SVK", "slovenska": "SVK", "slovenskému": "SVK",
    "česko": "CZE", "česká": "CZE", "cesko": "CZE", "ceska": "CZE",
    "norsko": "NOR", "norska": "NOR", "норsku": "NOR",
    "rusko": "RUS", "ruska": "RUS", "rusland": "RUS",
    "kazachstan": "KAZ", "kazachstanu": "KAZ", "kazakhstan": "KAZ",
    "švédsko": "SWE", "svedsko": "SWE", "svenska": "SWE", "sveska": "SWE", "svedsku": "SWE",
}

TEAM_CODE_ALIASES = {
    "CES": "CZE",
    "SVE": "SWE",
    "SVY": "SUI",
    "NEM": "GER",
    "KAN": "CAN",
    "DAN": "DEN",
}

KNOWN_TEAM_CODES = set(TEAM_MAPPING.values())


def parse_tl_live_feed_events(feed_text: str) -> List[Dict[str, str]]:
    """Vyparsuje tl_* feed na seznam radku oddelenych klicem TR."""
    item_separator = chr(172)
    key_separator = chr(247)
    events: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None

    for token in feed_text.split(item_separator):
        if key_separator not in token:
            continue

        key, value = token.split(key_separator, 1)
        key = key.lstrip("~")

        if key == "TR":
            if current:
                events.append(current)
            current = {}

        if current is not None:
            current[key] = value

    if current:
        events.append(current)

    return events


def infer_live_period_from_tl_row(row: Dict[str, str]) -> Optional[str]:
    """Odvodi tretinu z LM pole tl_* feedu."""
    period = (row.get("LM") or "").strip()
    if period in {"1", "2", "3"}:
        return f"{period}T"

    joined_text = " ".join(
        _strip_bbcode((row.get(key) or "").strip()) for key in ("LST", "LT", "LU", "LN", "LO", "LV", "LX")
    )
    period_match = re.search(r"\b([123])\.\s*t[řr]etina\b", joined_text, flags=re.IGNORECASE)
    if period_match:
        return f"{period_match.group(1)}T"

    return None


def _extract_clock(text: str) -> Optional[str]:
    if not text:
        return None

    match = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if match:
        return match.group(1)

    minute_match = re.search(r"\b(\d{1,2}')\b", text)
    if minute_match:
        return minute_match.group(1)

    return None


def _strip_bbcode(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"\[/?[a-zA-Z]+\]", "", text)
    return clean.replace("[br]", " ").strip()


def infer_live_details_from_tl_row(row: Dict[str, str]) -> tuple[Optional[str], Optional[str]]:
    """Vraci (live_clock, live_status) z tl_* radku."""
    lst_text = _strip_bbcode(row.get("LST") or "")
    lst_lower = lst_text.lower()

    if "konec" in lst_lower:
        return None, "Konec"
    if "přestáv" in lst_lower or "prestav" in lst_lower:
        return None, "Přestávka"

    ib_clock = _extract_clock((row.get("IB") or "").strip())
    if ib_clock:
        return ib_clock.split(":", 1)[0], None

    for key in ("LT", "LU", "LN", "LO", "LV", "LX"):
        clock = _extract_clock((row.get(key) or "").strip())
        if clock:
            return clock.split(":", 1)[0], None

    clock = _extract_clock(lst_text)
    if clock:
        return clock.split(":", 1)[0], None

    return None, None


def _period_label_to_code(label: str) -> Optional[str]:
    if not label:
        return None
    match = re.search(r"\b([123])\.\s*t[řr]etina\b", label, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}T"
    return None


def _extract_window_environment(page_html: str) -> Optional[Dict]:
    marker = "window.environment = "
    start = page_html.find(marker)
    if start == -1:
        return None

    json_start = page_html.find("{", start)
    if json_start == -1:
        return None

    depth = 0
    json_end = -1
    for idx in range(json_start, len(page_html)):
        char = page_html[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                json_end = idx
                break

    if json_end == -1:
        return None

    try:
        return json.loads(page_html[json_start : json_end + 1])
    except json.JSONDecodeError:
        return None


def fetch_live_minute_from_match_page(
    home_team_id: str,
    away_team_id: str,
    team_slug_map: Dict[str, str],
    headers: Dict[str, str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Vraci (live_period, live_clock, live_status) z detail stranky zapasu."""
    home_slug = (team_slug_map.get(home_team_id) or "").strip()
    away_slug = (team_slug_map.get(away_team_id) or "").strip()
    if not home_slug or not away_slug:
        return None, None, None

    match_url = f"https://www.livesport.cz/zapas/hokej/{away_slug}-{away_team_id}/{home_slug}-{home_team_id}/"
    page_headers = {"User-Agent": headers.get("User-Agent", "Mozilla/5.0")}

    try:
        response = requests.get(match_url, headers=page_headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None, None, None

    env = _extract_window_environment(response.text)
    if not env:
        return None, None, None

    stage_id = env.get("eventStageId")
    stage_to_period = {14: "1T", 15: "2T", 16: "3T"}
    live_period = stage_to_period.get(stage_id)

    live_status = None
    if stage_id == 46:
        live_status = "Přestávka"
    elif stage_id == 3:
        live_status = "Konec"

    live_clock = None
    common_feed = env.get("common_feed") or []
    for item in common_feed:
        if not isinstance(item, dict) or "DI" not in item:
            continue
        try:
            minute = int(item["DI"])
        except (TypeError, ValueError):
            continue
        if minute >= 0:
            live_clock = f"{minute}'"
        break

    return live_period, live_clock, live_status


def fetch_live_details_from_match_feed(event_id: str, headers: Dict[str, str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fallback na detailni df_sui_1_<eventId> feed pro periodu."""
    detail_url = f"https://1.flashscore.ninja/1/x/feed/df_sui_1_{event_id}"

    try:
        response = requests.get(detail_url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None, None, None

    feed_text = response.text
    item_separator = chr(172)
    key_separator = chr(247)

    latest_period_label: Optional[str] = None

    for token in feed_text.split(item_separator):
        if key_separator not in token:
            continue

        key, value = token.split(key_separator, 1)
        key = key.lstrip("~")
        value = value.strip()

        if key == "AC":
            latest_period_label = value

    period_code = _period_label_to_code(latest_period_label or "")
    return period_code, None, None


def normalize_tl_score_to_home_away(row: Dict[str, str], score_left: int, score_right: int) -> tuple[int, int]:
    """Prevede skore z tl_* radku na poradi home:away."""
    home_team_id = row.get("LSH")
    away_team_id = row.get("LSA")
    row_team_id = row.get("TI") or row.get("LMH")

    if row_team_id and home_team_id and away_team_id:
        if row_team_id == home_team_id:
            return score_left, score_right
        if row_team_id == away_team_id:
            return score_right, score_left

    lst_text = row.get("LST") or ""
    lst_score_match = re.search(r"\[b\](\d+:\d+)\[/b]", lst_text)
    if lst_score_match:
        lst_home, lst_away = parse_score(lst_score_match.group(1))
        if lst_home is not None and lst_away is not None:
            return lst_home, lst_away

    return score_left, score_right


def extract_tournament_ids(page_html: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Vraci (tournament_id, stage_id, feed_sign) z HTML."""
    tournament_id_match = re.search(r'tournamentId:\s*"([A-Za-z0-9]+)"', page_html)
    stage_id_match = re.search(r'tournamentStageId:\s*"([A-Za-z0-9]+)"', page_html)
    feed_sign_match = re.search(r'"feed_sign"\s*:\s*"([^"]+)"', page_html)

    tournament_id = tournament_id_match.group(1) if tournament_id_match else None
    stage_id = stage_id_match.group(1) if stage_id_match else None
    feed_sign = feed_sign_match.group(1) if feed_sign_match else None
    return tournament_id, stage_id, feed_sign


def fetch_live_table_matches(page_html: str, headers: Dict[str, str]) -> List[Dict]:
    """Stahne a vyparsuje LIVE zapasy z tl_* feedu live tabulky."""
    tournament_id, stage_id, feed_sign = extract_tournament_ids(page_html)
    if not tournament_id or not stage_id or not feed_sign:
        print("[CHYBA] Nelze z HTML ziskat tournamentId/stageId/feed_sign", file=sys.stderr)
        return []

    tl_url = f"https://1.flashscore.ninja/1/x/feed/tl_{tournament_id}_{stage_id}"
    tl_headers = dict(headers)
    tl_headers["Referer"] = "https://www.livesport.cz/"
    tl_headers["x-fsign"] = feed_sign

    try:
        tl_response = requests.get(tl_url, headers=tl_headers, timeout=10)
        tl_response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[CHYBA] Nelze stahnout tl_* live feed: {exc}", file=sys.stderr)
        return []

    tl_feed = tl_response.text

    team_slug_map: Dict[str, str] = {}
    slug_map_match = re.search(r'~PIU÷(\{.*?\})(?:¬|$)', tl_feed)
    if slug_map_match:
        try:
            team_slug_map = json.loads(slug_map_match.group(1))
        except json.JSONDecodeError:
            team_slug_map = {}

    rows = parse_tl_live_feed_events(tl_feed)
    live_matches = []
    seen_event_ids = set()

    for row in rows:
        event_id = row.get("LSE")
        if not event_id or event_id in seen_event_ids:
            continue

        score_text = row.get("LS") or row.get("LG")
        score_home, score_away = parse_score(score_text or "")
        if score_home is None or score_away is None:
            continue

        home_team_id = row.get("LSH")
        away_team_id = row.get("LSA")
        if not home_team_id or not away_team_id:
            continue

        score_home, score_away = normalize_tl_score_to_home_away(row, score_home, score_away)

        home_slug = (team_slug_map.get(home_team_id) or "").replace("-", " ")
        away_slug = (team_slug_map.get(away_team_id) or "").replace("-", " ")
        home_code = normalize_team_name(home_slug)
        away_code = normalize_team_name(away_slug)
        if not home_code or not away_code:
            continue

        timestamp = row.get("LMC")
        if not timestamp:
            continue

        try:
            dt = datetime.fromtimestamp(int(timestamp))
        except (ValueError, OSError):
            continue

        live_period = infer_live_period_from_tl_row(row)
        live_clock, live_status = infer_live_details_from_tl_row(row)

        page_period, page_clock, page_status = fetch_live_minute_from_match_page(
            home_team_id,
            away_team_id,
            team_slug_map,
            headers,
        )
        has_authoritative_status = page_status in {"Přestávka", "Konec"}
        if page_period:
            live_period = page_period
        elif page_status == "Přestávka":
            # Pri oficialni prestavce z detailu zapasu neukazujeme zastaralou tretinu z tl_* feedu.
            live_period = None
        if page_clock:
            live_clock = page_clock
        if page_status:
            live_status = page_status

        need_detail_fallback = (
            (live_period is None or live_clock is None or (live_status == "Přestávka")) and not has_authoritative_status
        )
        if event_id and need_detail_fallback:
            period_before = live_period
            detail_period, detail_clock, detail_status = fetch_live_details_from_match_feed(event_id, tl_headers)
            if detail_period:
                live_period = detail_period

            if (
                live_status == "Přestávka"
                and period_before
                and detail_period
                and detail_period != period_before
            ):
                live_status = None

            if detail_clock:
                live_clock = detail_clock
                if live_status == "Přestávka" and detail_period and detail_period != (period_before or detail_period):
                    live_status = None
            elif detail_status:
                live_status = detail_status

        live_matches.append(
            {
                "home": home_code,
                "away": away_code,
                "score_home": score_home,
                "score_away": score_away,
                "type": "LIVE",
                "live_period": live_period,
                "live_clock": live_clock,
                "live_status": live_status,
                "date": dt.strftime("%Y-%m-%d"),
                "time": dt.strftime("%H:%M"),
            }
        )
        seen_event_ids.add(event_id)

    return live_matches


def normalize_team_name(name: str) -> str:
    """Normalizuje nazev tymu na kod zeme."""
    name_lower = name.lower().strip()
    for key, code in TEAM_MAPPING.items():
        if key in name_lower:
            return code
    return None


def parse_score(score_text: str) -> tuple:
    """Parsuje skore z textu '3:2' na (3, 2)."""
    try:
        parts = score_text.strip().split(":")
        if len(parts) == 2:
            return int(parts[0].strip()), int(parts[1].strip())
    except (ValueError, IndexError):
        pass
    return None, None


def detect_match_type(score_text: str) -> str:
    """Detekuje typ zapasu (REG, OT, SO) z textu."""
    score_text_lower = score_text.lower()
    if "so" in score_text_lower or "sn" in score_text_lower:
        return "SO"
    if "ot" in score_text_lower or "pp" in score_text_lower:
        return "OT"
    return "REG"


def parse_feed_events(page_html: str, feed_name: str) -> List[Dict[str, str]]:
    """Vyparsuje encoded feed summary-results na seznam event tokenu."""
    feed_pattern = rf'cjs\.initialFeeds\["{re.escape(feed_name)}"\]\s*=\s*\{{\s*data:\s*`(.*?)`,'
    match = re.search(feed_pattern, page_html, re.S)
    if not match:
        print(f"[CHYBA] {feed_name} feed nebyl v HTML nalezen", file=sys.stderr)
        return []

    feed = match.group(1)
    item_separator = chr(172)
    key_separator = chr(247)
    events: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None

    for token in feed.split(item_separator):
        if key_separator not in token:
            continue

        key, value = token.split(key_separator, 1)
        key = key.lstrip("~")

        if key == "AA":
            if current:
                events.append(current)
            current = {}

        if current is not None:
            current[key] = value

    if current:
        events.append(current)

    return events


def parse_embedded_events(page_html: str) -> List[Dict[str, str]]:
    """Vyparsuje vsechny eventy z embedded token streamu v HTML (fallback)."""
    item_separator = chr(172)
    key_separator = chr(247)
    events: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None

    for token in page_html.split(item_separator):
        if key_separator not in token:
            continue

        key, value = token.split(key_separator, 1)
        key = key.lstrip("~")

        if key == "AA":
            if current:
                events.append(current)
            current = {}

        if current is not None:
            current[key] = value

    if current:
        events.append(current)

    return events


def normalize_team_code(raw_code: str) -> Optional[str]:
    if not raw_code:
        return None
    normalized = TEAM_CODE_ALIASES.get(raw_code.upper().strip(), raw_code.upper().strip())
    if normalized in KNOWN_TEAM_CODES:
        return normalized
    return None


def get_event_team_codes(event: Dict[str, str]) -> tuple[Optional[str], Optional[str]]:
    home_code = normalize_team_code(event.get("WM") or "")
    away_code = normalize_team_code(event.get("WN") or "")

    if not home_code:
        home_name = event.get("AE") or event.get("CX", "")
        home_code = normalize_team_name(home_name)

    if not away_code:
        away_name = event.get("AF", "")
        away_code = normalize_team_name(away_name)

    return home_code, away_code


def parse_match_type_from_periods(event: Dict[str, str], score_home: int, score_away: int) -> str:
    """Urci typ zapasu podle period skore; fallback je REG."""
    regulation_home = 0
    regulation_away = 0

    for home_key, away_key in (("BA", "BB"), ("BC", "BD"), ("BE", "BF")):
        try:
            regulation_home += int(event.get(home_key, "0"))
            regulation_away += int(event.get(away_key, "0"))
        except ValueError:
            return "REG"

    if (regulation_home, regulation_away) == (score_home, score_away):
        return "REG"

    status_text = " ".join([event.get("ER", ""), event.get("E2", ""), event.get("AW", "")]).lower()
    if "sn" in status_text or "naje" in status_text:
        return "SO"
    return "OT"


def detect_event_state(event: Dict[str, str]) -> str:
    """Vraci FINAL/SCHEDULED/LIVE dle stavove informace v eventu."""
    status_code = (event.get("AB") or "").strip()
    if status_code == "3":
        return "FINAL"
    if status_code == "1":
        return "SCHEDULED"

    status_text = " ".join([event.get("AW", ""), event.get("ER", ""), event.get("E2", "")]).lower()
    if "konec" in status_text:
        return "FINAL"
    if re.search(r"\b\d{1,2}:\d{2}\b", status_text):
        return "SCHEDULED"

    return "LIVE"


def infer_live_period(event: Dict[str, str]) -> Optional[str]:
    """Odvodi aktualni tretinu pro LIVE zapas."""
    status_text = " ".join([event.get("AW", ""), event.get("ER", ""), event.get("E2", "")]).lower()
    period_match = re.search(r"\b([123])\.\s*t[řr]etin", status_text)
    if period_match:
        return f"{period_match.group(1)}T"

    if "BE" in event or "BF" in event:
        return "3T"
    if "BC" in event or "BD" in event:
        return "2T"
    if "BA" in event or "BB" in event:
        return "1T"
    return None


def fetch_livesport_results() -> List[Dict]:
    """
    Stahne vysledky zapasu z livesport.cz.
    Vraci seznam slovniku: {"home": "FIN", "away": "GER", "score_home": 3, "score_away": 2, "type": "REG", "date": "2026-05-15", "time": "16:20"}
    """
    results = []

    try:
        print(f"[*] Stahuji data z {URL}...", file=sys.stderr)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(URL, headers=headers, timeout=10)
        response.raise_for_status()

        results_events = parse_feed_events(response.text, "summary-results")
        fixtures_events = parse_feed_events(response.text, "summary-fixtures")

        # live-tabulka muze mit docasne nekompletni summary-results; doplnime je z vysledky.
        results_events_by_id = {
            event.get("AA"): event for event in results_events if event.get("AA")
        }
        try:
            results_response = requests.get(RESULTS_URL, headers=headers, timeout=10)
            results_response.raise_for_status()
            results_page_events = parse_feed_events(results_response.text, "summary-results")
            embedded_events = parse_embedded_events(results_response.text)
            for event in (results_page_events + embedded_events):
                event_id = event.get("AA")
                if not event_id or event_id in results_events_by_id:
                    continue
                results_events.append(event)
                results_events_by_id[event_id] = event
        except requests.RequestException:
            # Fallback je best-effort; pri chybe zustaneme u live-tabulka feedu.
            pass

        events = results_events + fixtures_events
        live_matches = fetch_live_table_matches(response.text, headers)
        print(
            f"[*] Nalezeno {len(results_events)} result eventu a {len(fixtures_events)} fixture eventu",
            file=sys.stderr,
        )

        seen_ids = set()

        for event in events:
            event_id = event.get("AA")
            if not event_id or event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            event_state = detect_event_state(event)
            if event_state == "SCHEDULED":
                continue
            if "AG" not in event or "AH" not in event:
                continue

            try:
                score_home = int(event["AG"])
                score_away = int(event["AH"])
            except ValueError:
                continue

            home_code, away_code = get_event_team_codes(event)
            if not home_code or not away_code:
                continue

            try:
                dt = datetime.fromtimestamp(int(event["AD"]))
            except (KeyError, ValueError, OSError):
                continue

            if event_state == "FINAL":
                match_type = parse_match_type_from_periods(event, score_home, score_away)
                live_period = None
            else:
                match_type = "LIVE"
                live_period = infer_live_period(event)

            results.append(
                {
                    "home": home_code,
                    "away": away_code,
                    "score_home": score_home,
                    "score_away": score_away,
                    "type": match_type,
                    "live_period": live_period,
                    "date": dt.strftime("%Y-%m-%d"),
                    "time": dt.strftime("%H:%M"),
                }
            )

        by_match_key = {
            (match["home"], match["away"], match["date"], match["time"]): match for match in results
        }
        for live_match in live_matches:
            key = (live_match["home"], live_match["away"], live_match["date"], live_match["time"])
            if (live_match.get("live_status") or "").strip().lower() == "konec":
                continue
            by_match_key[key] = live_match

        results = list(by_match_key.values())

        print(f"[*] Nalezeno {len(results)} zapasu", file=sys.stderr)
        return results

    except requests.RequestException as exc:
        print(f"[CHYBA] Nelze pripojit na livesport.cz: {exc}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"[CHYBA] Chyba pri parsovani: {exc}", file=sys.stderr)
        return []


if __name__ == "__main__":
    results = fetch_livesport_results()
    print(json.dumps(results, indent=2, ensure_ascii=False))
