import cv2
import time
import sys
import os
from ultralytics import YOLO

# Add parent directory to sys.path to allow config import when running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config

def run_tracker(camera_source, reid_queue, ppe_queue, shared_results, track_to_person, stop_event):
    """
    Producer thread: reads camera, runs YOLOv8-pose + Bot-SORT tracking, 
    crops persons, and pushes data to separate Re-ID and PPE queues.
    """
    model = YOLO(config.POSE_WEIGHTS_PATH, task='pose')
    cap = cv2.VideoCapture(camera_source)
    if not cap.isOpened():
        print(f"Error: Could not open video source {camera_source}")
        return 

    # In-memory optimization helpers
    reid_processing_tracks = set()  # Tracks currently sent/processed by Re-ID
    last_ppe_push_time = {}         # track_id -> timestamp (push every 2s)

    while cap.isOpened() and not stop_event.is_set():
        success, frame = cap.read()

        if not success:
            print(f" Error: Cannot read frame from {camera_source}")
            # If playing a file, we might have reached the end. 
            # To avoid spinning, we can sleep slightly or break if it's a file
            time.sleep(0.01)
            continue
        
        results = model.track(
            source = frame,
            verbose = False,
            persist = True,
            tracker = "botsort.yaml",
            conf = config.TRACKER_CONF
        )

        if results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy() # take bounding box
            track_ids = results[0].boxes.id.cpu().numpy() # take track id

            # Extract keypoints from YOLOv8 pose model
            keypoints_data = None
            if hasattr(results[0], 'keypoints') and results[0].keypoints is not None and len(results[0].keypoints) > 0:
                keypoints_data = results[0].keypoints.data.cpu().numpy() # shape (N, 17, 3)

            current_time = time.time()

            for i, (box, track_id) in enumerate(zip(boxes, track_ids)):
                x1, y1, x2, y2 = map(int, box)
                crop_img = frame[y1:y2, x1:x2]

                # Adjust keypoints to be relative to the cropped bounding box
                relative_keypoints = None
                if keypoints_data is not None and i < len(keypoints_data):
                    relative_keypoints = keypoints_data[i].copy()
                    relative_keypoints[:, 0] -= x1
                    relative_keypoints[:, 1] -= y1

                # 1. Re-ID Queue: Push ONLY ONCE per track ID
                if track_id not in track_to_person and track_id not in reid_processing_tracks:
                    if not reid_queue.full():
                        reid_queue.put({
                            "track_id": track_id,
                            "crop_img": crop_img
                        })
                        reid_processing_tracks.add(track_id)

                # 2. PPE Queue: Push PERIODICALLY (every config interval)
                if current_time - last_ppe_push_time.get(track_id, 0) > config.PPE_CHECK_INTERVAL:
                    if not ppe_queue.full():
                        ppe_queue.put({
                            "track_id": track_id,
                            "crop_img": crop_img,
                            "keypoints": relative_keypoints
                        })
                        last_ppe_push_time[track_id] = current_time

                # 3. UI Display Color coding
                if track_id in shared_results:
                    display_text = shared_results[track_id] 
                    # Red if unknown or has violations, Green if clean employee
                    if "New" in display_text or "Violations" in display_text or "Unknown" in display_text:
                        box_color = (0, 0, 255) # Red for alert
                    else:
                        box_color = (0, 255, 0) # Green for OK
                else:
                    display_text = f"Tracking ID: {track_id} (Processing...)"
                    box_color = (0, 255, 255) # Yellow while processing

                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                cv2.putText(frame, display_text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)

        cv2.imshow("person re id real time demo", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            stop_event.set()
            break
    
    cap.release()
    cv2.destroyAllWindows()
