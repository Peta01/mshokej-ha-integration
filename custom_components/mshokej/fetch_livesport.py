#!/usr/bin/env python3
"""
Web scraping skript pro stažení výsledků zápasů z livesport.cz
Vrací JSON se seznamem zápasů s výsledky.
"""

import json
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional

import requests

URL = "https://www.livesport.cz/hokej/svet/mistrovstvi-sveta/live-tabulka/"

# Mapování názvů týmů z livesport.cz na kódy v MS 2026
TEAM_MAPPING = {
    "kanada": "CAN",
    "finsko": "FIN", "finska": "FIN",
    "nemecko": "GER", "německo": "GER", "německá": "GER",
    "usa": "USA",
    "švýcarsko": "SUI", "schweiz": "SUI",
    "svycarsko": "SUI",
    "británie": "GBR", "velká británie": "GBR", "anglie": "GBR",
    "velka britanie": "GBR",
    "rakousko": "AUT",
    "maďarsko": "HUN",
    "lotyšsko": "LAT",
    "lotyssko": "LAT",
    "francie": "FRA",
    "itálie": "ITA",
    "dánsko": "DEN", "dansko": "DEN",
    "slovinsko": "SLO",
    "slovensko": "SVK",
    "česko": "CZE", "česká": "CZE",
    "cesko": "CZE",
    "norsko": "NOR",
    "rusko": "RUS",
    "kazachstan": "KAZ",
    "švédsko": "SWE",
    "svedsko": "SWE",
}


def parse_tl_live_feed_events(feed_text: str) -> List[Dict[str, str]]:
    """Vyparsuje tl_* feed na seznam radku oddelenych klicem TR."""
    item_separator = chr(172)  # '¬'
    key_separator = chr(247)   # '÷'
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

    # Fallback: nektere varianty feedu posilaji periodu textove (napr. "2. třetina").
    joined_text = " ".join(
        _strip_bbcode((row.get(key) or "").strip())
        for key in ("LST", "LT", "LU", "LN", "LO", "LV", "LX")
    )
    period_match = re.search(r"\b([123])\.\s*t[řr]etina\b", joined_text, flags=re.IGNORECASE)
    if period_match:
        return f"{period_match.group(1)}T"

    return None


def _extract_clock(text: str) -> Optional[str]:
    if not text:
        return None

    # Prioritne bereme presny mm:ss format.
    match = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if match:
        return match.group(1)

    # Fallback pro sportovni feedy typu "4'" (minuta hry).
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
    if "konec" in lst_text.lower():
        return None, "Konec"

    ib_clock = _extract_clock((row.get("IB") or "").strip())
    if ib_clock:
        return ib_clock.split(":", 1)[0], None

    # Potencialni pole s casem v nekterych variantach feedu.
    for key in ("LT", "LU", "LN", "LO", "LV", "LX"):
        clock = _extract_clock((row.get(key) or "").strip())
        if clock:
            return clock.split(":", 1)[0], None

    clock = _extract_clock(lst_text)
    if clock:
        return clock.split(":", 1)[0], None

    # LC=3 u hokeje typicky odpovida prestavce mezi tretinami.
    if (row.get("LC") or "").strip() == "3":
        return None, "Přestávka"

    return None, None


def _period_label_to_code(label: str) -> Optional[str]:
    if not label:
        return None
    match = re.search(r"\b([123])\.\s*t[řr]etina\b", label, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}T"
    return None


def fetch_live_details_from_match_feed(event_id: str, headers: Dict[str, str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fallback na detailni df_sui_1_<eventId> feed pro periodu a orientacni cas."""
    detail_url = f"https://1.flashscore.ninja/1/x/feed/df_sui_1_{event_id}"

    try:
        response = requests.get(detail_url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None, None, None

    feed_text = response.text
    item_separator = chr(172)  # '¬'
    key_separator = chr(247)   # '÷'

    current_period_label: Optional[str] = None
    latest_period_label: Optional[str] = None
    last_clock: Optional[str] = None  # Poslední čas v mm:ss

    for token in feed_text.split(item_separator):
        if key_separator not in token:
            continue

        key, value = token.split(key_separator, 1)
        key = key.lstrip("~")
        value = value.strip()

        if key == "AC":
            current_period_label = value
            latest_period_label = value
            continue

        # IB = čas poslední akce v mm:ss - to je čas v třetině!
        if key == "IB" and re.match(r"^\d{1,2}:\d{2}$", value):
            last_clock = value
            continue

    period_code = _period_label_to_code(latest_period_label or "")
    clock = None
    if last_clock:
        try:
            minutes_str, seconds_str = last_clock.split(":", 1)
            minutes = int(minutes_str)
            seconds = int(seconds_str)
            clock = str(minutes + (1 if seconds > 0 else 0))
        except (ValueError, IndexError):
            clock = None

    return period_code, clock, None


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

    # Mapovani team internal id -> slug (cesko, svycarsko, ...)
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

        # Fallback: tl feed byva zpozdeny, takze VZDY ziskejme cas z detail feedu pro LIVE zapasy.
        # 1) Kdyz perioda chybi uplne, doplnime ji z detail feedu.
        # 2) VZDY se pokusime ziskat nejnovejsi cas z detail feedu (ten je presnejsi).
        # 3) Kdyz tl tvrdi "Prestavka", overime detail feed; pokud uz bezi dalsi tretina, prepneme periodu.
        need_detail_fallback = live_period is None or live_clock is None or (live_status == "Přestávka")
        if event_id and need_detail_fallback:
            period_before = live_period
            detail_period, detail_clock, detail_status = fetch_live_details_from_match_feed(event_id, tl_headers)
            if detail_period:
                live_period = detail_period

            # Pokud tl feed stale drzi Prestavku, ale detail uz ukazuje jinou tretinu,
            # povazujeme to za stale status a odstranime ho.
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
    """Normalizuje název týmu na kód země."""
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
        return "SO"  # Nájezdy
    elif "ot" in score_text_lower or "pp" in score_text_lower:
        return "OT"  # Prodloužení
    else:
        return "REG"  # Bezna doba


def parse_feed_events(page_html: str, feed_name: str) -> List[Dict[str, str]]:
    """Vyparsuje encoded feed summary-results na seznam event tokenu."""
    feed_pattern = rf'cjs\.initialFeeds\["{re.escape(feed_name)}"\]\s*=\s*\{{\s*data:\s*`(.*?)`,'
    match = re.search(feed_pattern, page_html, re.S)
    if not match:
        print(f"[CHYBA] {feed_name} feed nebyl v HTML nalezen", file=sys.stderr)
        return []

    feed = match.group(1)
    item_separator = chr(172)  # '¬'
    key_separator = chr(247)   # '÷'
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

    # Pokud finalni vysledek nesedi na 60 minut, jde o OT nebo SO.
    status_text = " ".join(
        [event.get("ER", ""), event.get("E2", ""), event.get("AW", "")]
    ).lower()
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

    # Fallback podle dostupnych periodovych poli ve feedu.
    if "BE" in event or "BF" in event:
        return "3T"
    if "BC" in event or "BD" in event:
        return "2T"
    if "BA" in event or "BB" in event:
        return "1T"
    return None


def fetch_livesport_results() -> List[Dict]:
    """
    Stáhne výsledky zápasů z livesport.cz.
    Vrací seznam slovníků: {"home": "FIN", "away": "GER", "score_home": 3, "score_away": 2, "type": "REG", "date": "2026-05-15", "time": "16:20"}
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

            # Zapasy jen s casem zacatku (nenarozhrane) ignorujeme.
            if event_state == "SCHEDULED":
                continue

            # Skore je jen u odehranych zapasu.
            if "AG" not in event or "AH" not in event:
                continue

            try:
                score_home = int(event["AG"])
                score_away = int(event["AH"])
            except ValueError:
                continue

            home_name = event.get("AE") or event.get("CX", "")
            away_name = event.get("AF", "")
            home_code = normalize_team_name(home_name)
            away_code = normalize_team_name(away_name)
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

        # tl_* feed vraci aktualni LIVE stavy (napr. 1. tretina 2:0),
        # ktere nemusi byt v summary feedu.
        by_match_key = {
            (m["home"], m["away"], m["date"], m["time"]): m for m in results
        }
        for live_match in live_matches:
            key = (live_match["home"], live_match["away"], live_match["date"], live_match["time"])
            if (live_match.get("live_status") or "").strip().lower() == "konec":
                continue
            by_match_key[key] = live_match

        results = list(by_match_key.values())

        print(f"[*] Nalezeno {len(results)} zapasu", file=sys.stderr)
        return results
    
    except requests.RequestException as e:
        print(f"[CHYBA] Nelze připojit na livesport.cz: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[CHYBA] Chyba při parsování: {e}", file=sys.stderr)
        return []


if __name__ == "__main__":
    results = fetch_livesport_results()
    print(json.dumps(results, indent=2, ensure_ascii=False))
