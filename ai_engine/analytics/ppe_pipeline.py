import queue
import time
import sys
import os
from ai_engine.analytics.ppe_detection import PPEDetector
from ai_engine.analytics.crop_body import get_crop
from database.queries import insert_violation

# Add parent directory to sys.path to allow config import when running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config

def run_ppe(ppe_queue, shared_results, track_to_person, stop_event):
    """
    Consumer thread for PPE Detection:
    1. Consumes crops and keypoints from ppe_queue.
    2. Checks if person_id is resolved by Re-ID thread.
    3. If resolved, runs PPE detection.
    4. Logs violations to database with state-based + time-based cooldown.
    5. Updates shared_results for UI display.
    """
    ppe_detector = PPEDetector()
    
    # Cooldown states
    last_violation_state = {}  # person_id -> (timestamp, violation_state_tuple)
    COOLDOWN_SECONDS = config.VIOLATION_COOLDOWN_SECONDS      # seconds between identical violations

    while not stop_event.is_set():
        try:
            data = ppe_queue.get(timeout=1)
            track_id = data["track_id"]
            crop_img = data["crop_img"]
            keypoints = data.get("keypoints")

            # Check if Re-ID has resolved the track_id
            person_id = track_to_person.get(track_id)
            if person_id is None:
                # Re-ID is still running, discard this frame (new ones will arrive)
                ppe_queue.task_done()
                continue

            # Crop body parts using keypoints
            body_crops = get_crop(crop_img, keypoints)

            # Detect violations
            violations = ppe_detector.detect_violations(body_crops)
            
            # Check if there is any violation
            has_violation = any(violations.values())
            
            # Format UI label
            if has_violation:
                violation_labels = []
                if violations['no_helmet']: violation_labels.append("No Helmet")
                if violations['no_glasses']: violation_labels.append("No Glasses")
                if violations['no_gloves']: violation_labels.append("No Gloves")
                if violations['no_vest']: violation_labels.append("No Vest")
                
                violations_str = ", ".join(violation_labels)
                shared_results[track_id] = f"Employee {person_id} [Violations: {violations_str}]"
                
                # Handle database logging with cooldown
                current_time = time.time()
                current_state = (
                    violations['no_helmet'],
                    violations['no_glasses'],
                    violations['no_gloves'],
                    violations['no_vest']
                )
                
                if person_id not in last_violation_state:
                    # Log to DB immediately on first violation
                    insert_violation(
                        person_id=person_id,
                        no_helmet=violations['no_helmet'],
                        no_glasses=violations['no_glasses'],
                        no_gloves=violations['no_gloves'],
                        no_vest=violations['no_vest']
                    )
                    last_violation_state[person_id] = (current_time, current_state)
                else:
                    last_time, last_state = last_violation_state[person_id]
                    # Log if state changed OR cooldown expired
                    if current_state != last_state or (current_time - last_time > COOLDOWN_SECONDS):
                        insert_violation(
                            person_id=person_id,
                            no_helmet=violations['no_helmet'],
                            no_glasses=violations['no_glasses'],
                            no_gloves=violations['no_gloves'],
                            no_vest=violations['no_vest']
                        )
                        last_violation_state[person_id] = (current_time, current_state)
            else:
                # No violation, reset display label
                shared_results[track_id] = f"Employee ID: {person_id}"

            ppe_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"PPE Thread Error: {e}")
            try:
                ppe_queue.task_done()
            except ValueError:
                pass