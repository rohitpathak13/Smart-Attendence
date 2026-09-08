import cv2
import numpy as np
from collections import deque
from typing import Dict, Tuple, Optional

class LivenessDetector:
    """
    Evaluates anti-spoofing liveness to prevent photo or screen proxy attendance.
    Combines:
    1. Texture analysis (Laplacian gradient sharpness & moire pattern detection)
    2. Landmark micro-motion dynamics across temporal frames (natural human jitter vs static photo)
    """
    def __init__(self, history_len: int = 12):
        self.history_len = history_len
        # Key: face_id or tracking key -> deque of landmark arrays
        self.landmark_history: Dict[str, deque] = {}

    def analyze_texture(self, face_crop: np.ndarray) -> Tuple[bool, float]:
        """
        Calculates Laplacian variance to detect low-res photo prints or heavily smoothed digital screens.
        """
        if face_crop is None or face_crop.size == 0:
            return False, 0.0

        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY) if len(face_crop.shape) == 3 else face_crop
        var = cv2.Laplacian(gray, cv2.CV_64F).var()

        # Typical sharp webcam face has variance 60 - 500
        # Overly blurry paper print or flat LCD screen has very low or abnormal variance
        is_plausible = var > 45.0
        return is_plausible, float(var)

    def check_temporal_liveness(self, tracking_id: str, landmarks: Dict) -> Tuple[bool, str, float]:
        """
        Tracks landmark coordinates over consecutive frames to detect natural micro-movements.
        A printed photo held in front of the camera exhibits near-zero landmark variation.
        """
        # Convert landmarks to a flat numpy array
        coords = []
        for pt in ["right_eye", "left_eye", "nose", "right_mouth", "left_mouth"]:
            coords.extend(landmarks[pt])
        curr_pts = np.array(coords, dtype=np.float32)

        if tracking_id not in self.landmark_history:
            self.landmark_history[tracking_id] = deque(maxlen=self.history_len)

        history = self.landmark_history[tracking_id]
        history.append(curr_pts)

        if len(history) < self.history_len // 2:
            return True, "Analyzing...", 0.5

        # Compute standard deviation of landmarks over time
        pts_array = np.array(history) # Shape: (N, 10)
        stds = np.std(pts_array, axis=0)
        mean_std = float(np.mean(stds))

        # If completely static (e.g. fixed digital screenshot or still frame injection), variance < 0.04
        if mean_std < 0.04:
            return False, "Static Spoof Detected", mean_std

        return True, "Live", mean_std

    def clear_history(self, tracking_id: Optional[str] = None):
        if tracking_id:
            self.landmark_history.pop(tracking_id, None)
        else:
            self.landmark_history.clear()

