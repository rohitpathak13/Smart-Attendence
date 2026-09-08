import cv2
import threading
import time
from typing import Tuple, Optional
import numpy as np

class ThreadedCamera:
    """
    Non-blocking camera capture using a background daemon thread.
    Prevents UI freezing and eliminates frame queue buffering latency.
    """
    def __init__(self, src: int = 0, width: int = 640, height: int = 480):
        self.src = src
        self.cap = cv2.VideoCapture(self.src, cv2.CAP_DSHOW) # CAP_DSHOW for fast startup on Windows
        if not self.cap.isOpened():
            # Fallback to default backend if DSHOW fails
            self.cap = cv2.VideoCapture(self.src)

        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)

        self.grabbed, self.frame = self.cap.read()
        self.started = False
        self.read_lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None

    def start(self):
        if self.started:
            return self
        self.started = True
        self.thread = threading.Thread(target=self.update, args=(), daemon=True)
        self.thread.start()
        return self

    def update(self):
        while self.started:
            if not self.cap.isOpened():
                time.sleep(0.1)
                continue
            grabbed, frame = self.cap.read()
            with self.read_lock:
                self.grabbed = grabbed
                self.frame = frame
            time.sleep(0.01) # Avoid hogging 100% CPU core

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.read_lock:
            if not self.grabbed or self.frame is None:
                return False, None
            return True, self.frame.copy()

    def release(self):
        self.started = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.cap.isOpened():
            self.cap.release()

    def is_opened(self) -> bool:
        return self.cap.isOpened()

