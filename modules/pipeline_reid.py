import queue
import numpy as np
import sys
import os
from modules.reid_inference import ReIDInference
from database.queries import load_gallery_features, insert_person

# Add parent directory to sys.path to allow config import when running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def run_reid(reid_queue, shared_results, track_to_person, weight_path, stop_event, threshold=None):
    """
    Consumer thread for Person Re-ID:
    1. Consumes crop images from reid_queue.
    2. Runs Re-ID to match or register person.
    3. Updates track_to_person and shared_results.
    """
    if threshold is None:
        threshold = config.REID_THRESHOLD
    if weight_path is None:
        weight_path = config.REID_WEIGHTS_PATH

    reid_brain = ReIDInference()
    local_gallery = load_gallery_features()

    while not stop_event.is_set():
        try:
            data = reid_queue.get(timeout=1)
            track_id = data["track_id"]
            crop_img = data["crop_img"]

            # Run feature extraction
            query_vector = reid_brain.extract_feature(crop_img)
            if query_vector is None:
                reid_queue.task_done()
                continue

            best_match_id = None
            min_distance = float('inf')

            for person in local_gallery:
                gallery_vector = person['vector']
                cosine_dist = 1.0 - np.dot(query_vector, gallery_vector)
                if cosine_dist < min_distance:
                    min_distance = cosine_dist
                    best_match_id = person['id']

            if min_distance <= threshold and best_match_id is not None:
                person_id = best_match_id
                shared_results[track_id] = f"Employee ID: {person_id}"
            else:
                person_id = insert_person(query_vector)
                local_gallery.append({
                    "id": person_id,
                    "vector": query_vector
                })
                shared_results[track_id] = f"New Employee: {person_id}"

            # Save mapping for PPE thread
            track_to_person[track_id] = person_id
            reid_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"Re-ID Thread Error: {e}")
            try:
                reid_queue.task_done()
            except ValueError:
                pass
