from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_LAST_UPDATE,
    ATTR_REFRESH_PLAN,
    ATTR_SNAPSHOT,
    ATTR_UPDATED_MATCHES,
    ATTR_WARNINGS,
    DOMAIN,
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SnapshotSensor(coordinator, entry),
            NextMatchSensor(coordinator, entry),
            FavoriteTeamPositionSensor(coordinator, entry),
            RefreshModeSensor(coordinator, entry),
        ]
    )


class BaseMSHokejSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_has_entity_name = True

    @property
    def available(self):
        return self.coordinator.data is not None


class SnapshotSensor(BaseMSHokejSensor):
    _attr_name = "Snapshot"
    _attr_icon = "mdi:hockey-puck"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_snapshot"

    @property
    def native_value(self):
        return self.coordinator.data.get(ATTR_LAST_UPDATE)

    @property
    def extra_state_attributes(self):
        return {
            ATTR_SNAPSHOT: self.coordinator.data.get(ATTR_SNAPSHOT),
            ATTR_REFRESH_PLAN: self.coordinator.data.get(ATTR_REFRESH_PLAN),
            ATTR_UPDATED_MATCHES: self.coordinator.data.get(ATTR_UPDATED_MATCHES, []),
            ATTR_WARNINGS: self.coordinator.data.get(ATTR_WARNINGS, []),
            "last_error": self.coordinator.data.get("last_error"),
        }


class NextMatchSensor(BaseMSHokejSensor):
    _attr_name = "Next match"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_next_match"

    @property
    def native_value(self):
        next_match = self.coordinator.data.get(ATTR_SNAPSHOT, {}).get("next_match")
        if not next_match:
            return None
        try:
            return dt_util.as_local(datetime.fromisoformat(f"{next_match['date']}T{next_match['time']}:00"))
        except (KeyError, ValueError):
            return None

    @property
    def extra_state_attributes(self):
        return self.coordinator.data.get(ATTR_SNAPSHOT, {}).get("next_match")


class FavoriteTeamPositionSensor(BaseMSHokejSensor):
    _attr_name = "Favorite team position"
    _attr_icon = "mdi:trophy-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_favorite_team_position"

    @property
    def native_value(self):
        snapshot = self.coordinator.data.get(ATTR_SNAPSHOT, {})
        favorite_team = snapshot.get("favorite_team")
        for group_name in ("A", "B"):
            for row in snapshot.get("groups", {}).get(group_name, []):
                if row.get("team") == favorite_team:
                    return row.get("position")
        return None

    @property
    def extra_state_attributes(self):
        snapshot = self.coordinator.data.get(ATTR_SNAPSHOT, {})
        favorite_team = snapshot.get("favorite_team")
        for group_name in ("A", "B"):
            for row in snapshot.get("groups", {}).get(group_name, []):
                if row.get("team") == favorite_team:
                    return {"team": favorite_team, "group": group_name, "points": row.get("points")}
        return {"team": favorite_team}


class RefreshModeSensor(BaseMSHokejSensor):
    _attr_name = "Refresh mode"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_refresh_mode"

    @property
    def native_value(self):
        return self.coordinator.data.get(ATTR_REFRESH_PLAN, {}).get("mode")

    @property
    def extra_state_attributes(self):
        return self.coordinator.data.get(ATTR_REFRESH_PLAN, {})
