"""
MJPEG streaming: serves annotated frames from each camera worker at
/stream/{camera_id} using multipart/x-mixed-replace.

The camera worker writes its latest annotated frame into a shared buffer;
this module reads and encodes it. Good enough for 2 cameras on a LAN —
upgrade path is WebRTC (MediaMTX) if sub-200ms latency is ever needed.
"""
import time

# TODO(streaming): wire to the camera workers' shared-memory frame buffers.
FRAME_INTERVAL = 1 / 25  # cap at 25 fps per client


def mjpeg_generator(get_latest_jpeg):
    """
    get_latest_jpeg: callable returning the newest JPEG bytes for a camera
    (or None when the camera is offline).
    """
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    while True:
        jpeg = get_latest_jpeg()
        if jpeg is not None:
            yield boundary + jpeg + b"\r\n"
        time.sleep(FRAME_INTERVAL)
