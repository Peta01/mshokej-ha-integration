import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_LAST_UPDATE,
    ATTR_REFRESH_PLAN,
    ATTR_SNAPSHOT,
    ATTR_UPDATED_MATCHES,
    ATTR_WARNINGS,
    CONF_FAVORITE_TEAM,
    CONF_IDLE_POLL_INTERVAL,
    CONF_LIVE_POLL_INTERVAL,
    CONF_PRE_MATCH_BUFFER,
    CONF_TITLE,
    DEFAULT_FAVORITE_TEAM,
    DEFAULT_IDLE_POLL_INTERVAL,
    DEFAULT_LIVE_POLL_INTERVAL,
    DEFAULT_PRE_MATCH_BUFFER,
    DEFAULT_TITLE,
    DOMAIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .fetch_livesport import fetch_livesport_results
from .live_update import update_results_dataset
from .refresh_policy import compute_refresh_plan
from .snapshot import build_snapshot

LOGGER = logging.getLogger(__name__)


class MSHokejDataCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._results = None
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry.entry_id}")

        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_IDLE_POLL_INTERVAL),
        )

    @property
    def title(self) -> str:
        return self.entry.options.get(CONF_TITLE, self.entry.data.get(CONF_TITLE, DEFAULT_TITLE))

    @property
    def favorite_team(self) -> str:
        return self.entry.options.get(CONF_FAVORITE_TEAM, self.entry.data.get(CONF_FAVORITE_TEAM, DEFAULT_FAVORITE_TEAM)).upper()

    @property
    def live_poll_interval(self) -> int:
        return int(
            self.entry.options.get(
                CONF_LIVE_POLL_INTERVAL,
                self.entry.data.get(CONF_LIVE_POLL_INTERVAL, DEFAULT_LIVE_POLL_INTERVAL),
            )
        )

    @property
    def pre_match_buffer(self) -> int:
        return int(
            self.entry.options.get(
                CONF_PRE_MATCH_BUFFER,
                self.entry.data.get(CONF_PRE_MATCH_BUFFER, DEFAULT_PRE_MATCH_BUFFER),
            )
        )

    @property
    def idle_poll_interval(self) -> int:
        return int(
            self.entry.options.get(
                CONF_IDLE_POLL_INTERVAL,
                self.entry.data.get(CONF_IDLE_POLL_INTERVAL, DEFAULT_IDLE_POLL_INTERVAL),
            )
        )

    async def _async_load_initial_results(self):
        if self._results is not None:
            return self._results

        stored = await self._store.async_load()
        if stored:
            self._results = stored
            return self._results

        schedule_path = Path(__file__).resolve().parent / "schedule.json"
        raw_schedule = await self.hass.async_add_executor_job(schedule_path.read_text, "utf-8")
        self._results = json.loads(raw_schedule)
        await self._store.async_save(self._results)
        return self._results

    async def _async_refresh_once(self):
        livesport_data = await self.hass.async_add_executor_job(fetch_livesport_results)
        update_result = await self.hass.async_add_executor_job(update_results_dataset, self._results, livesport_data)
        self._results = update_result["results"]
        await self._store.async_save(self._results)
        return update_result

    async def _async_build_payload(self, update_result, last_error=None):
        now = datetime.now()
        refresh_plan = await self.hass.async_add_executor_job(
            compute_refresh_plan,
            self._results["matches"],
            now,
            self.live_poll_interval,
            self.pre_match_buffer,
            self.idle_poll_interval,
        )
        snapshot = await self.hass.async_add_executor_job(
            build_snapshot,
            self._results["matches"],
            self.title,
            self.favorite_team,
            now,
            refresh_plan["mode"],
            refresh_plan["seconds"],
            refresh_plan["next_refresh_at"],
        )
        self.update_interval = timedelta(seconds=max(1, int(refresh_plan["seconds"])))

        payload = {
            ATTR_SNAPSHOT: snapshot,
            ATTR_REFRESH_PLAN: {
                "mode": refresh_plan["mode"],
                "seconds": refresh_plan["seconds"],
                "next_match_start": refresh_plan["next_match_start"].isoformat() if refresh_plan["next_match_start"] else None,
                "next_refresh_at": refresh_plan["next_refresh_at"].isoformat() if refresh_plan["next_refresh_at"] else None,
            },
            ATTR_LAST_UPDATE: snapshot["meta"]["generated_at"],
            ATTR_UPDATED_MATCHES: update_result.get("updated_matches", []),
            ATTR_WARNINGS: update_result.get("warnings", []),
            "last_error": last_error,
        }
        return payload

    def _retry_refresh_plan(self, now):
        next_refresh_at = now + timedelta(seconds=self.live_poll_interval)
        return {
            "mode": "retry",
            "seconds": self.live_poll_interval,
            "next_match_start": None,
            "next_refresh_at": next_refresh_at,
        }

    async def _async_update_data(self):
        await self._async_load_initial_results()

        try:
            update_result = await self._async_refresh_once()
            return await self._async_build_payload(update_result)
        except Exception as err:
            if self._results is None:
                raise UpdateFailed(str(err)) from err

            now = datetime.now()
            refresh_plan = self._retry_refresh_plan(now)
            snapshot = await self.hass.async_add_executor_job(
                build_snapshot,
                self._results["matches"],
                self.title,
                self.favorite_team,
                now,
                refresh_plan["mode"],
                refresh_plan["seconds"],
                refresh_plan["next_refresh_at"],
            )
            self.update_interval = timedelta(seconds=max(1, int(refresh_plan["seconds"])))

            return {
                ATTR_SNAPSHOT: snapshot,
                ATTR_REFRESH_PLAN: {
                    "mode": refresh_plan["mode"],
                    "seconds": refresh_plan["seconds"],
                    "next_match_start": None,
                    "next_refresh_at": refresh_plan["next_refresh_at"].isoformat(),
                },
                ATTR_LAST_UPDATE: snapshot["meta"]["generated_at"],
                ATTR_UPDATED_MATCHES: [],
                ATTR_WARNINGS: [str(err)],
                "last_error": str(err),
            }
