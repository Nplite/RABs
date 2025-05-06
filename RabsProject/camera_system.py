import logging
import cv2
import time
import numpy as np
from typing import Optional
from threading import Thread, Lock
import queue
import cv2
import numpy as np
import time
import os, sys
import csv
from datetime import datetime
from math import ceil, sqrt
import threading
from collections import deque
from typing import Optional, Any
from ultralytics import YOLO
logging.getLogger('ultralytics').setLevel(logging.WARNING)
from vidgear.gears import CamGear
from RabsProject.logger import logging
from RabsProject.exception import RabsException
from RabsProject.mongodb import MongoDBHandlerSaving  
from RabsProject.mon import MongoDBHandlerSaving  
from RabsProject.send_email import EmailSender
from RabsProject.utils import save_snapshot, send_data_to_dashboard

frame_queues = {}
MAX_QUEUE_SIZE = 30  

motion_buffer_duration = 5  
moton_buffer_fps = 25
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
motion_frame_buffer = deque(maxlen=moton_buffer_fps * motion_buffer_duration)  
recording_after_detection = False
ResurveTime = float(os.getenv("RESURVE_TIME", "10"))




email = EmailSender(cc_email='namdeopatil.1995@gmail.com')


class CameraStream:
    """Handles video streaming from RTSP cameras with improved error handling and frame management"""
    try:
        def __init__(self, rtsp_url: str, camera_id: int, buffer_size: int = 30):
            self.rtsp_url = rtsp_url
            self.camera_id = camera_id
            self.buffer_size = buffer_size
            self.frame_queue = queue.Queue(maxsize=buffer_size)
            self.stopped = False
            self.lock = Lock()
            self._initialize_stream()
            
        def _initialize_stream(self) -> None:
            """Initialize or reinitialize the camera stream"""
            try:
                self.cap = CamGear(source=self.rtsp_url, logging=True).start()
                self.fps = self.cap.stream.get(cv2.CAP_PROP_FPS)
                if not self.fps or self.fps <= 0:
                    self.fps = 30
                    logging.warning(f"Camera {self.camera_id}: Invalid FPS detected, defaulting to {self.fps}")
                logging.info(f"Camera {self.camera_id}: Initialized with FPS: {self.fps}")
            except RabsException as e:
                logging.error(f"Camera {self.camera_id}: Failed to initialize stream: {str(e)}")
                raise

        def start(self) -> 'CameraStream':
            """Start the frame capture thread"""
            self.capture_thread = Thread(target=self._update, daemon=True)
            self.capture_thread.start()
            return self

        def _update(self) -> None:
            """Continuously update frame buffer"""
            consecutive_failures = 0
            while not self.stopped:
                try:
                    with self.lock:
                        if self.frame_queue.full():
                            try:
                                self.frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        
                        frame = self.cap.read()
                        if frame is not None:
                            self.frame_queue.put(frame)
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            if consecutive_failures > 30:
                                logging.warning(f"Camera {self.camera_id}: Stream failure, attempting restart")
                                self._restart_stream()
                                consecutive_failures = 0
                                
                    time.sleep(1 / self.fps)
                    
                except RabsException as e:
                    logging.error(f"Camera {self.camera_id}: Frame capture error: {str(e)}")
                    time.sleep(1)

        def _restart_stream(self) -> None:
            """Restart the camera stream"""
            with self.lock:
                self.cap.stop()
                time.sleep(2)
                self._initialize_stream()

        def read(self) -> tuple[bool, Optional[np.ndarray]]:
            """Read the most recent frame"""
            try:
                frame = self.frame_queue.get_nowait()
                return True, frame
            except queue.Empty:
                return False, None

        def stop(self) -> None:
            """Stop the camera stream"""
            self.stopped = True
            with self.lock:
                self.cap.stop()
            if hasattr(self, 'capture_thread'):
                self.capture_thread.join(timeout=1.0)

    except Exception as e:
        raise RabsException(e, sys) from e


####################################################################################################################
                            ## Fire  Detection ##
####################################################################################################################



class MultiCameraSystemFire:
    try:
        """Manages multiple camera streams and their processing"""

        def __init__(self, email: str, model_path:str, category:str):
            self.email = email
            self.model_path = model_path
            self.category = category
            self.camera_processors = {}
            self.is_running = False
            self.mongo_handler = MongoDBHandlerSaving()
            self.last_frames = {}
            self._initialize_cameras()


        def _initialize_cameras(self) -> None:
            """Fetch camera details from MongoDB and initialize processors"""
            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(self.email, self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email}")
                return

            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]

                    processor = CameraProcessorFire(camera_id=camera_id, rtsp_url=rtsp_link, model_path=self.model_path, category=self.category)
                    processor.stream.start()
                    self.camera_processors[camera_id] = processor
                    self.last_frames[camera_id] = None
                    logging.info(f"Camera {camera_id}: Initialized successfully from MongoDB")
                except RabsException as e:
                    logging.error(f"Camera {camera_id}: Initialization failed: {str(e)}")

        def get_video_frames(self):
            """Generator function to yield video frames as bytes for HTTP streaming"""
            logging.info("Streaming multi-camera video frames")

            grid_cols = ceil(sqrt(len(self.camera_processors)))
            grid_rows = ceil(len(self.camera_processors) / grid_cols)
            blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)

            while True:
                frames = []
                for camera_id, processor in self.camera_processors.items():
                    if processor.stream.stopped:
                        continue
                    
                    ret, frame = processor.stream.read()
                    if ret:
                        processed_frame, _ = processor.process_frame(frame)
                        self.last_frames[camera_id] = processed_frame
                    else:
                        processed_frame = self.last_frames.get(camera_id, blank_frame)

                    frame_resized = cv2.resize(processed_frame, (320, 240))
                    frames.append(frame_resized)

                if frames:
                    while len(frames) < grid_rows * grid_cols:
                        frames.append(blank_frame)

                    rows = [np.hstack(frames[i * grid_cols:(i + 1) * grid_cols]) for i in range(grid_rows)]
                    grid_display = np.vstack(rows)

                    _, buffer = cv2.imencode(".jpg", grid_display)
                    yield (b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def stop(self) -> None:
            """Stop the camera system"""
            self.is_running = False
            for processor in self.camera_processors.values():
                processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info("Camera system stopped")

    except Exception as e:
        raise RabsException(e, sys) from e


class SingleCameraSystemFire:
    try:
        """Manages a single camera stream and its processing"""

        def __init__(self, camera_id: str, email: str, model_path: str, category: str):
            self.email = email
            self.camera_id = camera_id
            self.model_path = model_path
            self.category = category
            self.mongo_handler = MongoDBHandlerSaving()
            self.is_running = False
            self.last_frame = None


            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(email = self.email, category=self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email}")
                return


            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]
                    
                    self.processor = CameraProcessorFire(camera_id=camera_id, rtsp_url=rtsp_link, model_path=self.model_path, category=self.category)

                    logging.info(f"Single Camera {self.camera_id}: Initialized successfully")
                except Exception as e:
                    logging.error(f"Single Camera {self.camera_id}: Initialization failed: {str(e)}")
                    self.processor = None

        def start(self):
            """Starts the single camera stream"""
            if not self.processor:
                logging.error(f"Single Camera {self.camera_id}: Cannot start, processor is not initialized")
                return
            
            try:
                self.processor.stream.start()
                self.is_running = True
                logging.info(f"Single Camera {self.camera_id}: Stream started")
            except Exception as e:
                logging.error(f"Single Camera {self.camera_id}: Failed to start: {str(e)}")
                self.is_running = False

        def get_video_frames(self):
            """Generator function to yield video frames as bytes for HTTP streaming"""
            logging.info(f"Streaming video frames for Single Camera {self.camera_id}")
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

            while self.is_running:
                if self.processor and not self.processor.stream.stopped:
                    ret, frame = self.processor.stream.read()
                    if ret:
                        processed_frame, _ = self.processor.process_frame(frame)
                        self.last_frame = processed_frame
                    else:
                        logging.warning(f"Single Camera {self.camera_id}: Failed to read frame, using last frame")
                        processed_frame = self.last_frame if self.last_frame is not None else blank_frame
                else:
                    logging.error(f"Single Camera {self.camera_id}: Stream is stopped or processor is None")
                    processed_frame = blank_frame

                frame_resized = cv2.resize(processed_frame, (640, 480))
                _, buffer = cv2.imencode(".jpg", frame_resized)
                yield (b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" +
                    buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def stop(self):
            """Stops the camera stream and releases resources"""
            self.is_running = False
            if self.processor:
                self.processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info(f"Single Camera {self.camera_id}: Stream stopped")

    except Exception as e:
        raise RabsException(e, sys) from e


class CameraProcessorFire:
    def __init__(self, camera_id: int, rtsp_url: str, model_path: str, category:str, confidence=0.3):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.category   = category
        self.confidence = confidence
        self.stream = CameraStream(rtsp_url, camera_id)
        self.window_name = f'Camera {self.camera_id}'
        self.last_motion_time = None
        self.motion_frame_buffer = deque(maxlen=100)  # Buffer for motion frames
        self.recording_after_detection = False
        self.recording_end_time = None
        self.fourcc = cv2.VideoWriter_fourcc(*'XVID')  # Properly define fourcc
        self._initialize_model(model_path)

    def _initialize_model(self, model_path: str) -> None:
        try:
            self.model = YOLO(model_path)
            logging.info(f"Camera {self.camera_id}: Model initialized successfully")
        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Model initialization failed: {str(e)}")
            raise

    def process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, bool]:
        try:
            self.motion_frame_buffer.append(frame.copy())

            # Run inference with task='obb'
            results = self.model.predict(frame, task='obb', conf=self.confidence, verbose=False)
            result = results[0]
            annotated_frame = result.orig_img.copy()

            detected = False

            # Process Oriented Bounding Boxes
            if result.obb is not None:
                for i in range(len(result.obb.xywhr)):
                    x, y, w, h, angle = result.obb.xywhr[i].cpu().numpy()
                    cls = int(result.obb.cls[i].item())
                    conf = float(result.obb.conf[i].item())

                    # Assuming class 0 = fire
                    if cls == 0:
                        detected = True

                        # Create and draw the rotated bounding box
                        rect = ((x, y), (w, h), angle)
                        box = cv2.boxPoints(rect).astype(int)
                        cv2.polylines(annotated_frame, [box], isClosed=True, color=(0, 0, 255), thickness=2)

                        # Optional: draw class and confidence
                        label = f"{self.model.names[cls]} {conf:.2f}"
                        cv2.putText(annotated_frame, label, (box[0][0], box[0][1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

            if detected:
                self.current_time = datetime.now()
                if self.last_motion_time is None or (self.current_time - self.last_motion_time).total_seconds() > ResurveTime:
                    self.last_motion_time = self.current_time

                    snapshot_path = save_snapshot(frame=annotated_frame, camera_id=self.camera_id, category=self.category)
                    thread = threading.Thread(
                        target=send_data_to_dashboard,
                        args=(snapshot_path, self.current_time, self.camera_id, self.category))
                    thread.start()

            return annotated_frame, detected

        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Frame processing error: {str(e)}")
            return frame, False


####################################################################################################################
                            ## Smoke Detection ##
####################################################################################################################




class MultiCameraSystemSmoke:
    try:
        """Manages multiple camera streams and their processing"""

        def __init__(self, email: str, model_path:str, category:str):
            self.email = email
            self.model_path = model_path
            self.category = category
            self.camera_processors = {}
            self.is_running = False
            self.mongo_handler = MongoDBHandlerSaving()
            self.last_frames = {}
            self._initialize_cameras()


        def _initialize_cameras(self) -> None:
            """Fetch camera details from MongoDB and initialize processors"""
            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(self.email, self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email}")
                return

            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]

                    processor = CameraProcessorSmoke(camera_id=camera_id, rtsp_url=rtsp_link, model_path=self.model_path, category=self.category)
                    processor.stream.start()
                    self.camera_processors[camera_id] = processor
                    self.last_frames[camera_id] = None
                    logging.info(f"Camera {camera_id}: Initialized successfully from MongoDB")
                except RabsException as e:
                    logging.error(f"Camera {camera_id}: Initialization failed: {str(e)}")

        def get_video_frames(self):
            """Generator function to yield video frames as bytes for HTTP streaming"""
            logging.info("Streaming multi-camera video frames")

            grid_cols = ceil(sqrt(len(self.camera_processors)))
            grid_rows = ceil(len(self.camera_processors) / grid_cols)
            blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)

            while True:
                frames = []
                for camera_id, processor in self.camera_processors.items():
                    if processor.stream.stopped:
                        continue
                    
                    ret, frame = processor.stream.read()
                    if ret:
                        processed_frame, _ = processor.process_frame(frame)
                        self.last_frames[camera_id] = processed_frame
                    else:
                        processed_frame = self.last_frames.get(camera_id, blank_frame)

                    frame_resized = cv2.resize(processed_frame, (320, 240))
                    frames.append(frame_resized)

                if frames:
                    while len(frames) < grid_rows * grid_cols:
                        frames.append(blank_frame)

                    rows = [np.hstack(frames[i * grid_cols:(i + 1) * grid_cols]) for i in range(grid_rows)]
                    grid_display = np.vstack(rows)

                    _, buffer = cv2.imencode(".jpg", grid_display)
                    yield (b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def stop(self) -> None:
            """Stop the camera system"""
            self.is_running = False
            for processor in self.camera_processors.values():
                processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info("Camera system stopped")

    except Exception as e:
        raise RabsException(e, sys) from e


class SingleCameraSystemSmoke:
    try:
        """Manages a single camera stream and its processing"""

        def __init__(self, camera_id: str, email: str, model_path: str, category: str):
            self.email = email
            self.camera_id = camera_id
            self.model_path = model_path
            self.category = category
            self.mongo_handler = MongoDBHandlerSaving()
            self.is_running = False
            self.last_frame = None


            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(email = self.email, category=self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email}")
                return


            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]
                    
                    self.processor = CameraProcessorSmoke(camera_id=camera_id, rtsp_url=rtsp_link, model_path=self.model_path, category=self.category)

                    logging.info(f"Single Camera {self.camera_id}: Initialized successfully")
                except Exception as e:
                    logging.error(f"Single Camera {self.camera_id}: Initialization failed: {str(e)}")
                    self.processor = None

        def start(self):
            """Starts the single camera stream"""
            if not self.processor:
                logging.error(f"Single Camera {self.camera_id}: Cannot start, processor is not initialized")
                return
            
            try:
                self.processor.stream.start()
                self.is_running = True
                logging.info(f"Single Camera {self.camera_id}: Stream started")
            except Exception as e:
                logging.error(f"Single Camera {self.camera_id}: Failed to start: {str(e)}")
                self.is_running = False

        def get_video_frames(self):
            """Generator function to yield video frames as bytes for HTTP streaming"""
            logging.info(f"Streaming video frames for Single Camera {self.camera_id}")
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

            while self.is_running:
                if self.processor and not self.processor.stream.stopped:
                    ret, frame = self.processor.stream.read()
                    if ret:
                        processed_frame, _ = self.processor.process_frame(frame)
                        self.last_frame = processed_frame
                    else:
                        logging.warning(f"Single Camera {self.camera_id}: Failed to read frame, using last frame")
                        processed_frame = self.last_frame if self.last_frame is not None else blank_frame
                else:
                    logging.error(f"Single Camera {self.camera_id}: Stream is stopped or processor is None")
                    processed_frame = blank_frame

                frame_resized = cv2.resize(processed_frame, (640, 480))
                _, buffer = cv2.imencode(".jpg", frame_resized)
                yield (b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" +
                    buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def stop(self):
            """Stops the camera stream and releases resources"""
            self.is_running = False
            if self.processor:
                self.processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info(f"Single Camera {self.camera_id}: Stream stopped")

    except Exception as e:
        raise RabsException(e, sys) from e


class CameraProcessorSmoke:
    def __init__(self, camera_id: int, rtsp_url: str, model_path: str, category:str, confidence=0.3):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.category   = category
        self.confidence = confidence
        self.stream = CameraStream(rtsp_url, camera_id)
        self.window_name = f'Camera {self.camera_id}'
        self.last_motion_time = None
        self.motion_frame_buffer = deque(maxlen=100)  # Buffer for motion frames
        self.recording_after_detection = False
        self.recording_end_time = None
        self.fourcc = cv2.VideoWriter_fourcc(*'XVID')  # Properly define fourcc
        self._initialize_model(model_path)

    def _initialize_model(self, model_path: str) -> None:
        try:
            self.model = YOLO(model_path)
            logging.info(f"Camera {self.camera_id}: Model initialized successfully")
        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Model initialization failed: {str(e)}")
            raise

    def process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, bool]:
        try:
            self.motion_frame_buffer.append(frame.copy())

            # Run inference with task='obb'
            results = self.model.predict(frame, task='obb', conf=self.confidence, verbose=False)
            result = results[0]
            annotated_frame = result.orig_img.copy()

            detected = False

            # Process Oriented Bounding Boxes
            if result.obb is not None:
                for i in range(len(result.obb.xywhr)):
                    x, y, w, h, angle = result.obb.xywhr[i].cpu().numpy()
                    cls = int(result.obb.cls[i].item())
                    conf = float(result.obb.conf[i].item())

                    # Assuming class 0 = smoke
                    if cls == 0:
                        detected = True

                        # Create and draw the rotated bounding box
                        rect = ((x, y), (w, h), angle)
                        box = cv2.boxPoints(rect).astype(int)
                        cv2.polylines(annotated_frame, [box], isClosed=True, color=(0, 0, 255), thickness=2)

                        # Optional: draw class and confidence
                        label = f"{self.model.names[cls]} {conf:.2f}"
                        cv2.putText(annotated_frame, label, (box[0][0], box[0][1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

            if detected:
                self.current_time = datetime.now()
                if self.last_motion_time is None or (self.current_time - self.last_motion_time).total_seconds() > ResurveTime:
                    self.last_motion_time = self.current_time

                    snapshot_path = save_snapshot(frame=annotated_frame, camera_id=self.camera_id, category=self.category)
                    thread = threading.Thread(
                        target=send_data_to_dashboard,
                        args=(snapshot_path, self.current_time, self.camera_id, self.category)   )
                    thread.start()

            return annotated_frame, detected

        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Frame processing error: {str(e)}")
            return frame, False


####################################################################################################################
                              ## Safty Detection ##
####################################################################################################################



class MultiCameraSystemSafty:
    try:
        """Manages multiple camera streams and their processing"""

        def __init__(self, email: str, model_path:str, category:str):
            self.email = email
            self.model_path = model_path
            self.category = category
            self.camera_processors = {}
            self.is_running = False
            self.mongo_handler = MongoDBHandlerSaving()
            self.last_frames = {}
            self._initialize_cameras()


        def _initialize_cameras(self) -> None:
            """Fetch camera details from MongoDB and initialize processors"""
            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(self.email, self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email}")
                return

            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]

                    processor = CameraProcessorSafty(camera_id=camera_id, rtsp_url=rtsp_link, model_path=self.model_path, category=self.category)
                    processor.stream.start()
                    self.camera_processors[camera_id] = processor
                    self.last_frames[camera_id] = None
                    logging.info(f"Camera {camera_id}: Initialized successfully from MongoDB")
                except RabsException as e:
                    logging.error(f"Camera {camera_id}: Initialization failed: {str(e)}")

        def get_video_frames(self):
            """Generator function to yield video frames as bytes for HTTP streaming"""
            logging.info("Streaming multi-camera video frames")

            grid_cols = ceil(sqrt(len(self.camera_processors)))
            grid_rows = ceil(len(self.camera_processors) / grid_cols)
            blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)

            while True:
                frames = []
                for camera_id, processor in self.camera_processors.items():
                    if processor.stream.stopped:
                        continue
                    
                    ret, frame = processor.stream.read()
                    if ret:
                        processed_frame, _ = processor.process_frame(frame)
                        self.last_frames[camera_id] = processed_frame
                    else:
                        processed_frame = self.last_frames.get(camera_id, blank_frame)

                    frame_resized = cv2.resize(processed_frame, (320, 240))
                    frames.append(frame_resized)

                if frames:
                    while len(frames) < grid_rows * grid_cols:
                        frames.append(blank_frame)

                    rows = [np.hstack(frames[i * grid_cols:(i + 1) * grid_cols]) for i in range(grid_rows)]
                    grid_display = np.vstack(rows)

                    _, buffer = cv2.imencode(".jpg", grid_display)
                    yield (b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def stop(self) -> None:
            """Stop the camera system"""
            self.is_running = False
            for processor in self.camera_processors.values():
                processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info("Camera system stopped")

    except Exception as e:
        raise RabsException(e, sys) from e


class SingleCameraSystemSafty:
    def __init__(self, camera_id, email, model_path, category):
        try:
            self.email = email
            self.category = category
            self.camera_id = camera_id
            self.model_path = model_path
           
            self.mongo_handler = MongoDBHandlerSaving()
            self.is_running = False
            self.last_frame = None

            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(email=self.email, category=self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email}")
                return

            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]
                    
                    self.processor = CameraProcessorSafty(
                        camera_id=camera_id,
                        rtsp_url=rtsp_link,
                        model_path=self.model_path ,
                        category= self.category
                    )
                    logging.info(f"Single Camera {self.camera_id}: Initialized successfully")
                except Exception as e:
                    logging.error(f"Single Camera {self.camera_id}: Initialization failed: {str(e)}")
                    self.processor = None
        except Exception as e:
            raise RabsException(e, sys) from e

    def start(self):
        if not self.processor:
            logging.error(f"Single Camera {self.camera_id}: Cannot start, processor is not initialized")
            return
        
        try:
            self.processor.stream.start()
            self.is_running = True
            logging.info(f"Single Camera {self.camera_id}: Stream started")
        except Exception as e:
            logging.error(f"Single Camera {self.camera_id}: Failed to start: {str(e)}")
            self.is_running = False

    def get_video_frames(self):
        try:
            logging.info(f"Streaming video frames for Single Camera {self.camera_id}")
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

            while self.is_running:
                if self.processor and not self.processor.stream.stopped:
                    ret, frame = self.processor.stream.read()
                    if ret:
                        processed_frame, _ = self.processor.process_frame(frame)
                        self.last_frame = processed_frame
                    else:
                        logging.warning(f"Single Camera {self.camera_id}: Failed to read frame, using last frame")
                        processed_frame = self.last_frame if self.last_frame is not None else blank_frame
                else:
                    logging.error(f"Single Camera {self.camera_id}: Stream is stopped or processor is None")
                    processed_frame = blank_frame

                frame_resized = cv2.resize(processed_frame, (640, 480))
                _, buffer = cv2.imencode(".jpg", frame_resized)
                yield (b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" +
                    buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        except Exception as e:
            raise RabsException(e, sys) from e           

    def stop(self):
        """Stops the camera stream and releases resources"""
        self.is_running = False
        if self.processor:
            self.processor.stream.stop()
        cv2.destroyAllWindows()
        logging.info(f"Single Camera {self.camera_id}: Stream stopped")


class CameraProcessorSafty:
    def __init__(self, camera_id: int, rtsp_url: str, model_path: str, category:str, confidence=0.3):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.category  = category
        self.confidence = confidence
        self.stream = CameraStream(rtsp_url, camera_id)
        self.window_name = f'Camera {self.camera_id}'
        self.last_motion_time = None
        self.motion_frame_buffer = deque(maxlen=100)  # Buffer for motion frames
        self.recording_after_detection = False
        self.recording_end_time = None
        self.fourcc = cv2.VideoWriter_fourcc(*'XVID')  # Properly define fourcc
        self._initialize_model(model_path)

    def _initialize_model(self, model_path: str) -> None:
        try:
            self.model = YOLO(model_path)
            logging.info(f"Camera {self.camera_id}: Model initialized successfully")
        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Model initialization failed: {str(e)}")
            raise

    def process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, bool]:
        try:
            self.motion_frame_buffer.append(frame.copy())

            results = self.model(frame, conf=self.confidence, verbose=False)
            annotated_frame = results[0].plot()

            # Extract detection class labels
            detections = results[0].boxes
            detected = False

            if detections is not None and detections.cls is not None:
                class_ids = detections.cls.cpu().numpy().astype(int)
               
                detected = any(cls_id in [0] for cls_id in class_ids)

            if detected:
                self.current_time = datetime.now()
                if self.last_motion_time is None or (self.current_time - self.last_motion_time).total_seconds() > ResurveTime:
                    self.last_motion_time = self.current_time

                    snapshot_path = save_snapshot(frame=annotated_frame, camera_id=self.camera_id, category=self.category)
                    thread = threading.Thread(
                        target=send_data_to_dashboard,
                        args=(snapshot_path, self.current_time, self.camera_id, self.category) )
                    thread.start()

            return annotated_frame, detected

        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Frame processing error: {str(e)}")
            return frame, False



# ##################################################################################################################
#                               # Truck Loading and Unloading #
# ##################################################################################################################



class MultiCameraSystemTruck:
    try:
        def __init__(self, email: str, model_path : str, category : str, confidence=0.3, cooldown_period=60):
            self.email = email
            self.model_path = model_path
            self.category = category
            self.confidence = confidence
            self.cooldown_period = cooldown_period
            self.camera_processors = {}
            self.is_running = False
            self.mongo_handler = MongoDBHandlerSaving()
            self.last_frames = {}
            self._initialize_cameras()

        def _initialize_cameras(self) -> None:
            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(email = self.email, category = self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email} and {self.category}")
                return

            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]

                    polygon_points = None
                    if "polygonal_points" in camera and camera["polygonal_points"]:
                        try:
                            polygon_str = camera["polygonal_points"]
                            points_str = polygon_str.strip('[]').split('), (')

                            polygon_points = []
                            for point_str in points_str:
                                point_str = point_str.replace('(', '').replace(')', '')
                                x, y = map(int, point_str.split(','))
                                polygon_points.append((x, y))
                                
                            logging.info(f"Camera {camera_id}: Parsed polygon points: {polygon_points}")
                        except Exception as e:
                            logging.error(f"Camera {camera_id}: Failed to parse polygon points: {str(e)}")
                            polygon_points = None

                    processor = CameraProcessorTruckYOLO(
                        camera_id, rtsp_link, self.model_path,
                        polygon_points=polygon_points,  # Pass the parsed polygon points
                        confidence=self.confidence, 
                        cooldown_period=self.cooldown_period,
                        category=self.category)
                        
                    processor.stream.start()
                    self.camera_processors[camera_id] = processor
                    self.last_frames[camera_id] = None
                    logging.info(f"Camera {camera_id}: Initialized successfully from MongoDB")
                except RabsException as e:
                    logging.error(f"Camera {camera_id}: Initialization failed: {str(e)}")

        def get_video_frames(self):
            """Generator function to yield multi-camera video frames as bytes for HTTP streaming."""
            logging.info("Streaming multi-camera video frames")

            grid_cols = ceil(sqrt(len(self.camera_processors)))
            grid_rows = ceil(len(self.camera_processors) / grid_cols)
            blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)

            while True:
                frames = []
                for camera_id, processor in self.camera_processors.items():
                    if processor.stream.stopped:
                        continue

                    ret, frame = processor.stream.read()
                    frame = cv2.resize(frame, (1920,1080))
                    if ret:
                        processed_frame, _, _= processor.process_frame(frame)
                        self.last_frames[camera_id] = processed_frame
                    else:
                        processed_frame = self.last_frames.get(camera_id, blank_frame)

                    frame_resized = cv2.resize(processed_frame, (640, 480))
                    frames.append(frame_resized)

                if frames:
                    while len(frames) < grid_rows * grid_cols:
                        frames.append(blank_frame)

                    rows = [np.hstack(frames[i * grid_cols:(i + 1) * grid_cols]) for i in range(grid_rows)]
                    grid_display = np.vstack(rows)

                    _, buffer = cv2.imencode(".jpg", grid_display)
                    yield (b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def stop(self) -> None:
            """Stop the multi-camera system."""
            self.is_running = False
            for processor in self.camera_processors.values():
                processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info("Multi-camera system stopped")

        def get_all_statistics(self):
            """Retrieve tracking statistics for all cameras."""
            all_stats = {}
            for camera_id, processor in self.camera_processors.items():
                stats = processor.get_statistics()
                all_stats[camera_id] = stats
            return all_stats
    except Exception as e:
        raise RabsException(e, sys) from e


class CameraProcessorTruckYOLO:
    try:
        def __init__(self, camera_id: int, rtsp_url: str, model_path: str, category:str,
                    polygon_points=None, confidence=0.25, cooldown_period=60, truck_class=0):
            self.camera_id = camera_id
            self.rtsp_url = rtsp_url
            self.category = category
            self.stream = CameraStream(rtsp_url, camera_id)
            self.window_name = f'Camera {self.camera_id}'
            
            # Set polygon points from parameter or use default if None
            if polygon_points and len(polygon_points) >= 3:
                self.polygon = np.array(polygon_points, np.int32)
                logging.info(f"Camera {self.camera_id}: Using custom polygon: {polygon_points}")
            else:
                self.polygon = np.array([(571, 716), (825, 577), (1259, 616), (1256, 798)], np.int32)
                logging.info(f"Camera {self.camera_id}: Using default polygon")
            
            self.confidence = confidence
            self.truck_class = truck_class  # COCO class index for 'truck'
            
            # Timer settings
            self.cooldown_period = cooldown_period
            self.timer_active = False
            self.timer_start = None
            self.last_detection_time = None
            self.entry_times = {}
            self.tracking_data = []
            
            # Logging configuration
            self.log_file = f"tracking_log_camera_{self.camera_id}.csv"
            self.init_logging()
            
            self._initialize_model(model_path)

        def _initialize_model(self, model_path: str) -> None:
            """Initialize YOLO model"""
            try:
                self.model = YOLO(model_path)
                logging.info(f"Camera {self.camera_id}: Model initialized successfully")
            except RabsException as e:
                logging.error(f"Camera {self.camera_id}: Model initialization failed: {str(e)}")
                raise
        
        def init_logging(self):
            """Initialize logging to save tracking data to a CSV file."""
            with open(self.log_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Timestamp", "Duration(seconds)"])

        def log_tracking_data(self, duration):
            """Log tracking data to a CSV file."""
            with open(self.log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'), round(duration, 2)])

        def is_point_in_polygon(self, point):
            """Check if a point is inside the polygon."""
            if self.polygon is None:
                return False
            return cv2.pointPolygonTest(self.polygon, point, False) >= 0

        def format_time(self, seconds):
            """Format seconds into HH:MM:SS."""
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            seconds = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


        def draw_overlay(self, frame, boxes_info):
            """Draw visualization elements on the frame."""
            if self.polygon is not None:
                pts = self.polygon.reshape((-1, 1, 2))
                cv2.polylines(frame, [pts], True, (0, 255, 0), 2)

            if self.timer_active and self.timer_start is not None:
                elapsed_time = time.time() - self.timer_start
                timer_text = f"Loading Time: {self.format_time(elapsed_time)}"
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 1.0
                thickness = 2

                (text_width, text_height), _ = cv2.getTextSize(timer_text, font, font_scale, thickness)
                cv2.rectangle(frame, (10, 10), (20 + text_width, 40 + text_height), (0, 0, 0), -1)
                cv2.putText(frame, timer_text, (15, 35), font, font_scale, (255, 255, 255), thickness)

            for box_info in boxes_info:
                x1, y1, x2, y2 = box_info['bbox']
                is_inside = box_info['is_inside']
                track_id = box_info['track_id']
                center_point = box_info['center']

                color = (0, 255, 0) if is_inside else (255, 0, 0)
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                cv2.circle(frame, center_point, 5, (0, 0, 255), -1)
                label = f"ID: {track_id}"
                cv2.putText(frame, label, (int(x1), int(y1) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cv2.putText(frame, timestamp, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            
            return frame

        def process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, list, bool]:
            """Process a frame with object detection and truck tracking."""
            truck_in_polygon = False
            current_time = time.time()
            boxes_info = []
            
            # Run YOLO tracking
            results = self.model.track(frame, persist=True, conf=self.confidence, classes=[self.truck_class])
            
            if results and len(results) > 0:
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        if hasattr(box, 'cls') and box.cls.cpu().numpy()[0] == self.truck_class:
                            x1, y1, x2, y2 = box.xyxy.cpu().numpy()[0]
                            center_x = int((x1 + x2) / 2)
                            center_y = int((y1 + y2) / 2)
                            center_point = (center_x, center_y)

                            track_id = int(box.id.cpu().numpy()[0]) if hasattr(box, 'id') and box.id is not None else -1

                            if track_id != -1:
                                is_inside = self.is_point_in_polygon(center_point)
                                if is_inside:
                                    truck_in_polygon = True

                                boxes_info.append({
                                    'bbox': (x1, y1, x2, y2),
                                    'center': center_point,
                                    'track_id': track_id,
                                    'is_inside': is_inside
                                })


            annotated_frame = self.draw_overlay(frame.copy(), boxes_info)
            
            # Timer logic based on whether a truck is in the polygon
            if truck_in_polygon:
                if not self.timer_active:
                    self.timer_active = True
                    self.timer_start = current_time
                    logging.info(f"Camera {self.camera_id}: Truck entered region. Timer started at {self.timer_start}")
            else:
                if self.timer_active:
                    duration = current_time - self.timer_start
                    self.log_tracking_data(duration)
                    logging.info(f"Camera {self.camera_id}: Truck exited region. Duration: {duration:.2f}s")
                    self.timer_active = False
                    self.timer_start = None

            return annotated_frame, boxes_info, truck_in_polygon

    except Exception as e:
        raise RabsException(e, sys) from e


class SingleCameraSystemTruck:
    try:
        """Manages a single camera stream and its processing"""
        def __init__(self, camera_id: int,  email: str, model_path: str,  category:str, confidence=0.3, cooldown_period=60):
            self.email = email
            self.camera_id = camera_id
            self.model_path = model_path
            self.category = category
            self.confidence = confidence
            self.cooldown_period = cooldown_period
            self.mongo_handler = MongoDBHandlerSaving()
            self.is_running = False
            self.last_frame = None


            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(self.email, category = self.category )

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email} and {self.category}")
                return

            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]
                     
                    # Parse polygon points from the database
                    polygon_points = None
                    if "polygonal_points" in camera and camera["polygonal_points"]:
                        try:
                            # Convert the string representation of polygon points to actual list of tuples
                            polygon_str = camera["polygonal_points"]
                            # Remove brackets and split by commas
                            points_str = polygon_str.strip('[]').split('), (')
                            
                            # Parse each point
                            polygon_points = []
                            for point_str in points_str:
                                point_str = point_str.replace('(', '').replace(')', '')
                                x, y = map(int, point_str.split(','))
                                polygon_points.append((x, y))
                                
                            logging.info(f"Camera {camera_id}: Parsed polygon points: {polygon_points}")
                        except Exception as e:
                            logging.error(f"Camera {camera_id}: Failed to parse polygon points: {str(e)}")
                            polygon_points = None

                    self.processor = CameraProcessorTruckYOLO(
                        camera_id, rtsp_link, self.model_path, 
                        polygon_points=polygon_points,  # Pass the parsed polygon points
                        confidence=self.confidence, 
                        cooldown_period=self.cooldown_period, 
                        category=self.category)

                    logging.info(f"Single Camera {self.camera_id}: Initialized successfully")
                except Exception as e:
                    logging.error(f"Single Camera {self.camera_id}: Initialization failed: {str(e)}")
                    self.processor = None

        def start(self):
            """Starts the single camera stream"""
            if not self.processor:
                logging.error(f"Single Camera {self.camera_id}: Cannot start, processor is not initialized")
                return
            
            try:
                self.processor.stream.start()
                self.is_running = True
                logging.info(f"Single Camera {self.camera_id}: Stream started")
            except Exception as e:
                logging.error(f"Single Camera {self.camera_id}: Failed to start: {str(e)}")
                self.is_running = False

        def get_video_frames(self):
            """Generator function to yield video frames as bytes for HTTP streaming"""
            logging.info(f"Streaming video frames for Single Camera {self.camera_id}")
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

            while self.is_running:
                if self.processor and not self.processor.stream.stopped:
                    ret, frame = self.processor.stream.read()
                    if ret:
                        processed_frame, _, _ = self.processor.process_frame(frame)
                        self.last_frame = processed_frame
                    else:
                        logging.warning(f"Single Camera {self.camera_id}: Failed to read frame, using last frame")
                        processed_frame = self.last_frame if self.last_frame is not None else blank_frame
                else:
                    logging.error(f"Single Camera {self.camera_id}: Stream is stopped or processor is None")
                    processed_frame = blank_frame

                frame_resized = processed_frame #cv2.resize(processed_frame, (640, 480))
                _, buffer = cv2.imencode(".jpg", frame_resized)
                yield (b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" +
                    buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def stop(self):
            """Stops the camera stream and releases resources"""
            self.is_running = False
            if self.processor:
                self.processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info(f"Single Camera {self.camera_id}: Stream stopped")


    except Exception as e:
        raise RabsException(e, sys) from e




####################################################################################################################
                            ## Opencv GPU Streaming Fire  Detection ##
####################################################################################################################




sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# from Opencv_cuda.gpumat_tensor.utils.memory_repr_pytorch import opencv_gpu_mat_as_pytorch_tensor
# from Opencv_cuda.gpumat_tensor.utils.memory_repr_pytorch import *
import torch.cuda
from RabsProject.utils.memory_repr_pytorch import opencv_gpu_mat_as_pytorch_tensor





class CameraStreamGPU:
    def __init__(self, rtsp_url: str, camera_id: int):
        self.rtsp_url = rtsp_url
        self.camera_id = camera_id
        self.frame = None
        self.stopped = False

        params = cv2.cudacodec.VideoReaderInitParams()
        params.targetSz = (640, 640)
        params.minNumDecodeSurfaces = 10

        self.video_reader = cv2.cudacodec.createVideoReader(self.rtsp_url, params=params)
        self.video_reader.set(cv2.cudacodec.COLOR_FORMAT_BGR)

    def start(self) -> 'CameraStreamGPU':
        self.thread = Thread(target=self._update, daemon=True)
        self.thread.start()
        return self

    def _update(self) -> None:
        while not self.stopped:
            ret, gpu_frame = self.video_reader.nextFrame()
            if ret:
                self.frame = gpu_frame
            time.sleep(0.01)

    def read(self) -> tuple[bool, Optional[Any]]:
        return (self.frame is not None), self.frame

    def stop(self) -> None:
        self.stopped = True
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)
        del self.video_reader


class MultiCameraSystemGPU:
    try:
        def __init__(self, email: str, model_path:str, category:str):
            self.email = email
            self.model_path = model_path
            self.category = category
            self.camera_processors = {}
            self.is_running = False
            self.mongo_handler = MongoDBHandlerSaving()
            self.last_frames = {}
            self._initialize_cameras()


        def _initialize_cameras(self) -> None:
            camera_data = self.mongo_handler.fetch_camera_rtsp_by_email_and_category(email = self.email, category = self.category)

            if not camera_data:
                logging.error(f"No camera data found for email: {self.email} and {self.category}")
                return

            for camera in camera_data:
                try:
                    camera_id = camera["camera_id"]
                    rtsp_link = camera["rtsp_link"]

                    processor = CameraProcessorGPU(
                        camera_id, rtsp_link, self.model_path,
                        category=self.category)
                        
                    processor.stream.start()
                    self.camera_processors[camera_id] = processor
                    self.last_frames[camera_id] = None
                    logging.info(f"Camera {camera_id}: Initialized successfully from MongoDB")
                except RabsException as e:
                    logging.error(f"Camera {camera_id}: Initialization failed: {str(e)}")

        def get_video_frames(self):
            """Generator function to yield video frames as bytes for HTTP streaming"""
            logging.info("Streaming multi-camera video frames")

            grid_cols = ceil(sqrt(len(self.camera_processors)))
            grid_rows = ceil(len(self.camera_processors) / grid_cols)
            blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)

            while True:
                frames = []
                for camera_id, processor in self.camera_processors.items():
                    if processor.stream.stopped:
                        continue
                    
                    ret, frame = processor.stream.read()
                    if ret:
                        processed_frame, _ = processor.process_frame(frame)
                        self.last_frames[camera_id] = processed_frame
                    else:
                        processed_frame = self.last_frames.get(camera_id, blank_frame)

                    frame_resized = cv2.resize(processed_frame, (320, 240))
                    frames.append(frame_resized)

                if frames:
                    while len(frames) < grid_rows * grid_cols:
                        frames.append(blank_frame)

                    rows = [np.hstack(frames[i * grid_cols:(i + 1) * grid_cols]) for i in range(grid_rows)]
                    grid_display = np.vstack(rows)

                    _, buffer = cv2.imencode(".jpg", grid_display)
                    yield (b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        buffer.tobytes() + b"\r\n")

                time.sleep(0.05)  # Small delay to control FPS

        def start(self):
            self.is_running = True
            try:
                while self.is_running:
                    for processor in self.camera_processors.values():
                        if not processor.stream.stopped:
                            ret, frame = processor.stream.read()
                            if ret:
                                processor.process_frame(frame)
                    time.sleep(0.1)
            except KeyboardInterrupt:
                self.stop()

        def stop(self) -> None:
            """Stop the camera system"""
            self.is_running = False
            for processor in self.camera_processors.values():
                processor.stream.stop()
            cv2.destroyAllWindows()
            logging.info("Camera system stopped")

    except Exception as e:
        raise RabsException(e, sys) from e


class CameraProcessorGPU:
    def __init__(self, camera_id: int, rtsp_url: str, model_path: str, category:str):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.category   = category
        
        self.stream = CameraStreamGPU(rtsp_url, camera_id)
        self.window_name = f'Camera {self.camera_id}'
        self.last_motion_time = None
        self.motion_frame_buffer = deque(maxlen=100)  # Buffer for motion frames
        self.recording_after_detection = False
        self.recording_end_time = None
        self.fourcc = cv2.VideoWriter_fourcc(*'XVID')  # Properly define fourcc
        self._initialize_model(model_path)

    def _initialize_model(self, model_path: str) -> None:
        try:
            self.model = YOLO(model_path)
            logging.info(f"Camera {self.camera_id}: Model initialized successfully")
        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Model initialization failed: {str(e)}")
            raise

    def process_frame(self, gpu_frame) -> tuple[np.ndarray, bool]:
        try:
            tensor_frame = opencv_gpu_mat_as_pytorch_tensor(gpu_frame)
            tensor_frame = tensor_frame.to(dtype=torch.float32) / 255.0
            tensor_frame = tensor_frame.permute(2, 0, 1).unsqueeze(0).contiguous()

            results = self.model.predict(
                source=tensor_frame,
                device=0,
                verbose=False,
                task='obb',
            )

            result = results[0]
            annotated_frame = result.plot(im_gpu='Tensor')
            if isinstance(annotated_frame, torch.Tensor):
                annotated_frame = annotated_frame.permute(1, 2, 0).cpu().numpy()

            detected = False

            if result.obb is not None:
                for i in range(len(result.obb.xywhr)):
                    x, y, w, h, angle = result.obb.xywhr[i].cpu().numpy()
                    cls = int(result.obb.cls[i].item())
                    conf = float(result.obb.conf[i].item())

                    if cls == 0:
                        detected = True

            if detected:
                self.current_time = datetime.now()
                if self.last_motion_time is None or (self.current_time - self.last_motion_time).total_seconds() > ResurveTime:
                    self.last_motion_time = self.current_time
                    snapshot_path = save_snapshot(frame=annotated_frame, camera_id=self.camera_id, category=self.category)
                    thread = threading.Thread(
                        target=send_data_to_dashboard,
                        args=(snapshot_path, self.current_time, self.camera_id, self.category))
                    thread.start()

            return annotated_frame, detected

        except Exception as e:
            logging.error(f"Camera {self.camera_id}: Frame processing error: {str(e)}")
            return None, False


# ####################################################################################################################
#                                                 ## END ##
# ####################################################################################################################




