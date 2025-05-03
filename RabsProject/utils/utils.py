import os, sys
import cv2
import logging
from datetime import datetime
from RabsProject.logger import logging
from RabsProject.exception import RabsException
from RabsProject.mon import MongoDBHandlerSaving  
from RabsProject.aws import AWSConfig
from RabsProject.send_email import EmailSender

mongo_handler = MongoDBHandlerSaving()
aws = AWSConfig()
email = EmailSender()

# def save_snapshot(frame, camera_id):
#     try:
#         if frame is None:
#             raise ValueError("Frame is None. Ensure the input frame is valid and not empty.")

#         # Generate date and time strings
#         date_str = datetime.now().strftime('%Y-%m-%d')
#         time_str = datetime.now().strftime('%H-%M-%S')  # Use '-' for compatibility

#         # Create directory structure
#         directory = os.path.join('snapshots', date_str)
#         os.makedirs(directory, exist_ok=True)

#         # Generate filename with camera_id
#         filename = os.path.join(directory, f'camera_{camera_id}_{time_str}.jpg')

#         # Save the snapshot
#         success = cv2.imwrite(filename, frame)
#         if not success:
#             raise IOError(f"Failed to write frame to file: {filename}")

#         print(f"Snapshot saved: {filename}")
#         logging.info(f"Snapshot saving is done and it save in this path: {filename}")
        
#         return '/' + filename.replace('\\', '/') 

#     except Exception as e:
#         raise RabsException(e,sys) from e

def save_snapshot(frame, camera_id, category):
    try:
        if frame is None:
            raise ValueError("Frame is None. Ensure the input frame is valid and not empty.")

        # Generate date and time strings
        date_str = datetime.now().strftime('%Y-%m-%d')
        time_str = datetime.now().strftime('%H-%M-%S')  # Use '-' for compatibility

        # Create nested directory structure: snapshots/YYYY-MM-DD/category/
        directory = os.path.join('snapshots', date_str, category)
        os.makedirs(directory, exist_ok=True)

        # Generate filename with camera_id
        filename = os.path.join(directory, f'camera_{camera_id}_{time_str}.jpg')

        # Save the snapshot
        success = cv2.imwrite(filename, frame)
        if not success:
            raise IOError(f"Failed to write frame to file: {filename}")

        logging.info(f"Snapshot saved: {filename}")
        return '/' + filename.replace('\\', '/')  # Return path in URL-style format

    except Exception as e:
        logging.error(f"Snapshot saving error: {str(e)}")
        raise RabsException(e, sys) from e


def save_video():
    try:
    
        date_str = datetime.now().strftime('%Y-%m-%d')
        time_str = datetime.now().strftime('%H:%M:%S')
        directory = os.path.join('video', date_str)
        os.makedirs(directory, exist_ok=True)
        video_path = os.path.join(directory, f'{time_str}.mp4')
        print(video_path)
        logging.info(f"Video saving is done and it save in this path: {video_path}")

        return video_path
    
    except Exception as e:
        raise RabsException(e,sys) from e
    
def send_data_to_dashboard(snapshot_path, start_time, camera_id, category):
    try:
        # video_url = aws.upload_video_to_s3bucket(video_path, camera_id)
        # snapshot_url = aws.upload_snapshot_to_s3bucket(snapshot_path, camera_id)
        mongo_handler.save_snapshot_to_mongodb(snapshot_path, start_time, camera_id, category)
        # mongo_handler.save_video_to_mongodb(video_url, start_time, camera_id)
        # email.send_alert_email(snapshot_path, camera_id)

        logging.info(f"Data sending completed for camera_Id: {camera_id}.")
    except Exception as e:
        logging.info(f"Error sending data for camera {camera_id}: {str(e)}")





