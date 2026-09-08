import cv2
import numpy as np
import os
import sys
from typing import List, Dict, Tuple, Optional

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import (
    YUNET_MODEL_PATH,
    SFACE_MODEL_PATH,
    CONFIDENCE_THRESHOLD,
    NMS_THRESHOLD,
    COSINE_SIMILARITY_THRESHOLD
)

class FaceEngine:
    def __init__(
        self,
        yunet_path: str = YUNET_MODEL_PATH,
        sface_path: str = SFACE_MODEL_PATH,
        conf_threshold: float = CONFIDENCE_THRESHOLD,
        nms_threshold: float = NMS_THRESHOLD,
        cosine_threshold: float = COSINE_SIMILARITY_THRESHOLD
    ):
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.cosine_threshold = cosine_threshold

        # Initialize YuNet Face Detector
        self.detector = cv2.FaceDetectorYN.create(
            yunet_path,
            "",
            (320, 320),
            score_threshold=self.conf_threshold,
            nms_threshold=self.nms_threshold,
            top_k=5000
        )

        # Initialize SFace Face Recognizer
        self.recognizer = cv2.FaceRecognizerSF.create(sface_path, "")
        self._current_input_size = (320, 320)

    def set_frame_size(self, width: int, height: int):
        if self._current_input_size != (width, height):
            self.detector.setInputSize((width, height))
            self._current_input_size = (width, height)

    def detect_faces(self, frame: np.ndarray) -> List[Dict]:
        """
        Detects faces in the given BGR frame.
        Returns a list of face dictionaries containing:
        - bbox: (x, y, w, h)
        - landmarks: dict of 5 points (right_eye, left_eye, nose, right_mouth, left_mouth)
        - confidence: detection confidence score
        - raw: raw 15-value numpy vector needed for SFace alignment
        """
        h, w = frame.shape[:2]
        self.set_frame_size(w, h)

        ret, faces = self.detector.detect(frame)
        if faces is None or len(faces) == 0:
            return []

        results = []
        for face in faces:
            x, y, fw, fh = map(int, face[0:4])
            # Clamp coordinates to frame boundary
            x = max(0, x)
            y = max(0, y)
            fw = min(fw, w - x)
            fh = min(fh, h - y)

            landmarks = {
                "right_eye": (int(face[4]), int(face[5])),
                "left_eye": (int(face[6]), int(face[7])),
                "nose": (int(face[8]), int(face[9])),
                "right_mouth": (int(face[10]), int(face[11])),
                "left_mouth": (int(face[12]), int(face[13]))
            }
            score = float(face[14])

            results.append({
                "bbox": (x, y, fw, fh),
                "landmarks": landmarks,
                "confidence": score,
                "raw": face
            })

        return results

    def extract_embedding(self, frame: np.ndarray, raw_face: np.ndarray) -> np.ndarray:
        """
        Aligns and crops the detected face, then computes the 128-D ArcFace feature vector.
        """
        aligned_face = self.recognizer.alignCrop(frame, raw_face)
        feature = self.recognizer.feature(aligned_face)
        return feature.flatten()

    def compare_faces(self, feature1: np.ndarray, feature2: np.ndarray) -> float:
        """
        Computes Cosine Similarity between two 128-D feature vectors.
        Output score ranges roughly from -1.0 to 1.0 (higher = closer match).
        A score >= 0.60 indicates a strong match.
        """
        f1 = feature1.reshape(1, -1).astype(np.float32)
        f2 = feature2.reshape(1, -1).astype(np.float32)
        score = self.recognizer.match(f1, f2, cv2.FaceRecognizerSF_FR_COSINE)
        return float(score)

    def identify_face(
        self,
        live_feature: np.ndarray,
        registered_students: List[Dict],
        threshold: Optional[float] = None
    ) -> Tuple[Optional[Dict], float]:
        """
        Compares live_feature against all registered students.
        Returns (best_student_dict, best_score) if above threshold, else (None, best_score).
        """
        if not registered_students:
            return None, 0.0

        match_thresh = threshold if threshold is not None else self.cosine_threshold
        best_student = None
        best_score = -1.0

        for student in registered_students:
            score = self.compare_faces(live_feature, student["embedding"])
            if score > best_score:
                best_score = score
                best_student = student

        if best_score >= match_thresh:
            return best_student, best_score
        return None, best_score

