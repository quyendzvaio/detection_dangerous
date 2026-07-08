import numpy as np

def safe_crop(person_chip, x1, y1, x2, y2):
    h, w = person_chip.shape[:2]

    x1 = int(max(0, x1))
    y1 = int(max(0, y1))
    x2 = int(min(w, x2))
    y2 = int(min(h, y2))

    if x1 >= x2 or y1 >= y2:
        return None 

    return person_chip[y1:y2, x1:x2]

def get_crop(frame, keypoints):
    
    crops = {}

    chip_h, chip_w = frame.shape[:2]

    crops['head'] = safe_crop(frame, 0, 0, chip_w, int(chip_h * 0.3))

    crops['face'] = safe_crop(frame, int(chip_w * 0.1), int(chip_h * 0.05), int(chip_w * 0.9), int(chip_h * 0.25))

    if keypoints is not None and len(keypoints) > 12 and keypoints[5][2] > 0.3:
        shoulder_y = min(keypoints[5][1], keypoints[6][1])
        hip_y = max(keypoints[11][1], keypoints[12][1])
        
        crops['torso'] = safe_crop(frame, 0, shoulder_y - 15, chip_w, hip_y + 15)
    else:
        crops['torso'] = safe_crop(frame, int(chip_w * 0.1), int(chip_h * 0.25), int(chip_w * 0.9), int(chip_h * 0.75))

    crops['hand'] = np.array([])
    if keypoints is not None and len(keypoints) > 10:
        left_wrist = keypoints[9]
        right_wrist = keypoints[10]

        best_wrist = left_wrist if left_wrist[2] > right_wrist[2] else right_wrist

        if best_wrist[2] > 0.2:
            hand_y = best_wrist[1]
            hand_x = best_wrist[0]
            crops['hand'] = safe_crop(frame, hand_x - 10, hand_y - 10, hand_x + 10, hand_y + 10)
    
    return crops


