import os

# ==============================================================================
# GENERAL SETTINGS
# ==============================================================================
# Camera source: 0 for webcam, or string path to video file (e.g. "test_media/test.mp4")
CAMERA_SOURCE = 0

# Enable GPU acceleration (CUDA) if available
USE_GPU = True

# Max size of queues to prevent memory overload
QUEUE_MAX_SIZE = 50

# ==============================================================================
# MODEL PATHS
# ==============================================================================
# Path to Re-ID model weights
REID_WEIGHTS_PATH = "weights/re_id_weights/model-v1.pth"

# Path to YOLOv8 pose model weights
POSE_WEIGHTS_PATH = "weights/yolov8n-pose.pt"

# Directory containing 4 classification weights for PPE (head, face, hand, torso)
PPE_WEIGHTS_DIR = "weights/PPE_weights"
HEAD_WEIGHTS_PATH = "http://localhost:8000/ppe_head"
FACE_WEIGHTS_PATH = "http://localhost:8000/ppe_face"
HAND_WEIGHTS_PATH = "http://localhost:8000/ppe_hand"
TORSO_WEIGHTS_PATH = "http://localhost:8000/ppe_torso"

# ==============================================================================
# DATABASE SETTINGS
# ==============================================================================
# Path to SQLite database file
DB_PATH = "database/factory.db"

# ==============================================================================
# DETECTION PARAMETERS & TIMINGS
# ==============================================================================
# Re-ID Cosine Distance Threshold (lower values mean stricter matching)
REID_THRESHOLD = 0.3

# Confidence threshold for YOLO pose tracker
TRACKER_CONF = 0.5

# Time interval (seconds) to run PPE detection check for each tracked person
PPE_CHECK_INTERVAL = 2.0

# Cooldown duration (seconds) before logging the exact same violation to database
VIOLATION_COOLDOWN_SECONDS = 30
