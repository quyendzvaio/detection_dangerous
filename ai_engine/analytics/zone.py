import cv2
import numpy as np


class ZoneChecker:
    """
    Restricted-zone intrusion detection (CPU-only, runs every frame).

    Zones are polygons defined per-camera (drawn on the frontend, stored in the
    `zones` table). A person is considered inside a zone when their foot point
    (bottom-center of the bbox) falls inside the polygon for `debounce_frames`
    consecutive frames — this filters out tracker jitter.
    """

    def __init__(self, zones=None, debounce_frames=5):
        """
        zones: list of dicts [{"id": int, "name": str, "polygon": [[x, y], ...]}]
               Coordinates are absolute pixels in the camera frame.
        """
        self.debounce_frames = debounce_frames
        self._zones = []
        self._inside_counts = {}  # (track_id, zone_id) -> consecutive frame count
        if zones:
            self.set_zones(zones)

    def set_zones(self, zones):
        """Replace the active zone list (called when zones change in DB)."""
        self._zones = [
            {
                "id": z["id"],
                "name": z.get("name", f"zone-{z['id']}"),
                "polygon": np.array(z["polygon"], dtype=np.int32),
            }
            for z in zones
        ]
        self._inside_counts.clear()

    @staticmethod
    def foot_point(bbox):
        """Bottom-center of bbox (x1, y1, x2, y2) — approximates feet position."""
        x1, _, x2, y2 = bbox
        return (int((x1 + x2) / 2), int(y2))

    def check(self, track_id, bbox):
        """
        Returns a list of zone dicts the track has *confirmed* intruded into
        (debounce passed) on this frame. Empty list means no confirmed intrusion.
        """
        point = self.foot_point(bbox)
        confirmed = []

        for zone in self._zones:
            key = (track_id, zone["id"])
            inside = cv2.pointPolygonTest(zone["polygon"], point, False) >= 0

            if inside:
                self._inside_counts[key] = self._inside_counts.get(key, 0) + 1
                if self._inside_counts[key] == self.debounce_frames:
                    confirmed.append(zone)
            else:
                self._inside_counts.pop(key, None)

        return confirmed

    def active_zone_ids(self, track_id):
        """Return zones whose intrusion debounce is currently satisfied.

        ``check`` intentionally returns a zone only once, at the moment the
        debounce threshold is crossed, so the event pipeline does not create a
        violation on every frame. The preview overlay has a different need: it
        must know the current state on every frame in order to remove the
        danger styling immediately when a person leaves the polygon.
        """
        return tuple(
            zone_id
            for (candidate_track_id, zone_id), count in self._inside_counts.items()
            if candidate_track_id == track_id and count >= self.debounce_frames
        )

    def drop_track(self, track_id):
        """Clean up state when a track disappears."""
        for key in [k for k in self._inside_counts if k[0] == track_id]:
            del self._inside_counts[key]
