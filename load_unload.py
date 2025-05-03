import cv2
from ultralytics import YOLO
import time
from datetime import datetime
import numpy as np
import logging
import csv



class TruckTracker:
    def __init__(self, model_path, video_path, polygon_points, confidence=0.25, cooldown_period=60):
        """Initialize the truck tracker with model and video paths."""
        self.model = YOLO(model_path)
        self.video_path = video_path
        self.polygon = np.array(polygon_points, np.int32)
        self.confidence = confidence
        self.truck_class = 0  # COCO class index for 'truck'
        self.entry_times = {}
        self.tracking_data = []

        # Timer settings
        self.cooldown_period = cooldown_period
        self.timer_active = False
        self.timer_start = None
        self.last_detection_time = None

        # Logging configuration
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
        self.log_file = "tracking_log.csv"
        self.init_logging()

    def init_logging(self):
        """Initialize logging to save tracking data to a CSV file."""
        with open(self.log_file, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Duration (seconds)"])

    def log_tracking_data(self, duration):
        """Log tracking data to a CSV file."""
        with open(self.log_file, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'), round(duration, 2)])

    def is_point_in_polygon(self, point):
        """Check if a point is inside the polygon."""
        return cv2.pointPolygonTest(self.polygon, point, False) >= 0

    def format_time(self, seconds):
        """Format seconds into HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def draw_overlay(self, frame, boxes_info):
        """Draw visualization elements on the frame."""
        # Draw polygon
        pts = self.polygon.reshape((-1, 1, 2))
        cv2.polylines(frame, [pts], True, (0, 255, 0), 2)

        # Draw timer if active
        if self.timer_active and self.timer_start is not None:
            elapsed_time = time.time() - self.timer_start
            timer_text = f"Loading Time: {self.format_time(elapsed_time)}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 1.0
            thickness = 2

            (text_width, text_height), _ = cv2.getTextSize(timer_text, font, font_scale, thickness)
            cv2.rectangle(frame, (10, 10), (20 + text_width, 40 + text_height), (0, 0, 0), -1)
            cv2.putText(frame, timer_text, (15, 35), font, font_scale, (255, 255, 255), thickness)

        # Draw detection boxes and their info
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

        # Add timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cv2.putText(frame, timestamp, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    def manage_timer(self, truck_detected_in_polygon, current_time):
        """Manage the timer state with cooldown period."""
        if truck_detected_in_polygon:
            if not self.timer_active:
                self.timer_active = True
                self.timer_start = current_time
            self.last_detection_time = current_time
        elif self.timer_active:
            if (current_time - self.last_detection_time) > self.cooldown_period:
                duration = current_time - self.timer_start
                self.tracking_data.append({'duration': duration, 'timestamp': datetime.now()})
                self.log_tracking_data(duration)
                self.timer_active = False
                self.timer_start = None

    def process_video(self, display=True, output_path=None):
        """Process the video and track trucks."""
        cap = cv2.VideoCapture(self.video_path)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))

        if output_path:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (frame_width, frame_height))

        try:
            while cap.isOpened():
                success, frame = cap.read()
                if not success:
                    break

                current_time = time.time()
                boxes_info = []
                truck_in_polygon = False

                # Run YOLO tracking
                results = self.model.track(frame, persist=True, conf=self.confidence, classes=[self.truck_class])

                if results and len(results) > 0:
                    boxes = results[0].boxes
                    if boxes is not None and len(boxes) > 0:
                        for box in boxes:
                            if box.cls.cpu().numpy()[0] == self.truck_class:
                                x1, y1, x2, y2 = box.xyxy.cpu().numpy()[0]
                                center_x = int((x1 + x2) / 2)
                                center_y = int((y1 + y2) / 2)
                                center_point = (center_x, center_y)

                                track_id = int(box.id.cpu().numpy()[0]) if box.id is not None else -1

                                if track_id != -1:
                                    is_inside = self.is_point_in_polygon(center_point)
                                    if is_inside:
                                        truck_in_polygon = True

                                    boxes_info.append({
                                        'bbox': (x1, y1, x2, y2),
                                        'center': center_point,
                                        'track_id': track_id,
                                        'is_inside': is_inside  })

                self.manage_timer(truck_in_polygon, current_time)
                self.draw_overlay(frame, boxes_info)

                if display:
                    cv2.imshow("Truck Tracking", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

                if output_path:
                    out.write(frame)

        finally:
            if self.timer_active and self.timer_start is not None:
                duration = time.time() - self.timer_start
                self.tracking_data.append({'duration': duration, 'timestamp': datetime.now()})
                self.log_tracking_data(duration)

            cap.release()
            if output_path:
                out.release()
            cv2.destroyAllWindows()

    def get_statistics(self):
        """Calculate and return time statistics."""
        if not self.tracking_data:
            return "No tracking data available."

        durations = [data['duration'] for data in self.tracking_data]
        stats = {
            'total_sessions': len(durations),
            'avg_duration': np.mean(durations),
            'min_duration': np.min(durations),
            'max_duration': np.max(durations),
            'std_duration': np.std(durations)
        }
        return stats

if __name__ == "__main__":
    tracker = TruckTracker(
        model_path="truck.pt",
        video_path="Videos/rabs.mp4",
        polygon_points=[(571, 716), (825, 577), (1259, 616), (1256, 798)],
        confidence=0.3,
        cooldown_period=60
    )

    tracker.process_video(display=True, output_path="output_tracking.mp4")

    stats = tracker.get_statistics()
    print("\nTracking Statistics:")
    for key, value in stats.items():
        print(f"{key}: {value:.2f}")
