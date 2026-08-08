import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))

from ai_engine.analytics.zone import ZoneChecker


def test_active_zone_is_cleared_when_track_leaves_polygon():
    checker = ZoneChecker(
        zones=[
            {
                "id": 42,
                "name": "restricted",
                "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]],
            }
        ],
        debounce_frames=2,
    )
    inside_bbox = np.array([20, 20, 60, 80], dtype=np.float32)
    outside_bbox = np.array([120, 20, 160, 80], dtype=np.float32)

    assert checker.check("cam1-7", inside_bbox) == []
    assert checker.active_zone_ids("cam1-7") == ()

    confirmed = checker.check("cam1-7", inside_bbox)
    assert [zone["id"] for zone in confirmed] == [42]
    assert checker.active_zone_ids("cam1-7") == (42,)

    assert checker.check("cam1-7", outside_bbox) == []
    assert checker.active_zone_ids("cam1-7") == ()
