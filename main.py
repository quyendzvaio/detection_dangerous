import threading
from queue import Queue
import os

import config
from database.connection import initialize_database
from ai_engine.analytics.reid_pipeline import run_reid
from ai_engine.analytics.ppe_pipeline import run_ppe
from ai_engine.workers.tracker import run_tracker

def main():
    weights_path = config.REID_WEIGHTS_PATH
    camera_source = config.CAMERA_SOURCE
    reid_threshold = config.REID_THRESHOLD

    if not os.path.exists(weights_path):
        print(f"Weight file not found at {weights_path}")
        return

    initialize_database()

    # Separate queues to prevent bottlenecking, sized by config
    reid_queue = Queue(maxsize = config.QUEUE_MAX_SIZE)
    ppe_queue = Queue(maxsize = config.QUEUE_MAX_SIZE)
    
    # Shared variables
    shared_result = {}      # track_id -> Display text for UI
    track_to_person = {}    # track_id -> resolved person_id (bridging Re-ID and PPE threads)

    stop_event = threading.Event()

    tracker_thread = threading.Thread(
        target = run_tracker,
        args = (
            camera_source,
            reid_queue,
            ppe_queue,
            shared_result,
            track_to_person,
            stop_event
        )
    )

    reid_thread = threading.Thread(
        target = run_reid,
        args = (
            reid_queue,
            shared_result,
            track_to_person,
            weights_path,
            stop_event,
            reid_threshold
        )
    )

    ppe_thread = threading.Thread(
        target = run_ppe,
        args = (
            ppe_queue,
            shared_result,
            track_to_person,
            stop_event
        )
    )

    print("Starting tracking, Re-ID, and PPE threads...")
    tracker_thread.start()
    reid_thread.start()
    ppe_thread.start()

    tracker_thread.join()
    reid_thread.join()
    ppe_thread.join()

    print("All threads finished.")

if __name__ == "__main__":
    main()
            