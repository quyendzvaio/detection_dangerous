"""Small production entrypoint; stream orchestration is config-driven."""

from __future__ import annotations

import os
import time
import json
from urllib.parse import quote, urlsplit, urlunsplit

from edge_agent.client import EdgeAgentClient, EdgeAgentConfig
from edge_agent.stream_publish import PublishSpec, StreamProcessManager


def main() -> int:
    control_plane_url = os.environ.get("CONTROL_PLANE_URL")
    credential = os.environ.get("DEVICE_CREDENTIAL")
    if not control_plane_url or not credential:
        raise SystemExit("CONTROL_PLANE_URL and DEVICE_CREDENTIAL are required")
    interval = float(os.environ.get("EDGE_HEARTBEAT_SECONDS", "30"))
    ingress_url = os.environ.get("MEDIA_MTX_INGRESS_URL")
    source_map = json.loads(os.environ.get("EDGE_CAMERA_SOURCES", "{}"))
    client = EdgeAgentClient(EdgeAgentConfig(control_plane_url, credential))
    publishers = StreamProcessManager()

    def authenticated_ingress(base_url: str) -> str:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
            raise SystemExit("MEDIA_MTX_INGRESS_URL must be an RTSP/RTSPS URL")
        return urlunsplit((
            parsed.scheme,
            f"{quote(os.environ.get('DEVICE_KEY', 'edge'), safe='')}:{quote(credential, safe='')}@{parsed.hostname}{':' + str(parsed.port) if parsed.port else ''}",
            parsed.path.rstrip("/"),
            parsed.query,
            parsed.fragment,
        ))

    authenticated_base = authenticated_ingress(ingress_url) if ingress_url else None
    try:
        while True:
            client.heartbeat()
            config = client.get_config()
            if ingress_url:
                for stream in config.get("streams", []):
                    source = source_map.get(stream["camera_key"])
                    if not source:
                        continue
                    publishers.ensure(
                        stream["camera_key"],
                        PublishSpec(
                            source=source,
                            target_rtsp_url=f"{authenticated_base.rstrip('/')}/{stream['path']}",
                            source_is_device=str(source).startswith("/dev/"),
                        ),
                    )
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    finally:
        publishers.close()
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
