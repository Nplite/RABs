import logging
import os, sys
from datetime import datetime, timedelta
from pymongo import MongoClient
from bcrypt import hashpw, gensalt
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

ALLOWED_CATEGORIES = {"fire", "smoke", "ppe", "truck"}

class MongoDBHandlerSaving:
    def __init__(self, url=os.getenv("MONGODB_URL_ACCESS"), db_name="RabsProject", 
                 user_collection_name="UserAuth", snapshot_collection_name='Snapshots', 
                 video_collection_name='Videos'):
        try:
            self.client = MongoClient(url)
            self.db = self.client[db_name]
            self.user_collection = self.db[user_collection_name]
            self.snapshot_collection = self.db[snapshot_collection_name]
            self.video_collection = self.db[video_collection_name]
            logger.info("Connected to MongoDB successfully")
        except Exception as e:
            logger.exception("Error connecting to MongoDB")
            raise


    def close_connection(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")


    @staticmethod
    def hash_password(password):
        return hashpw(password.encode(), gensalt()).decode()


    def save_user_to_mongodb(self, user_data, category, camera_info:None):
        try:
            existing_user = self.user_collection.find_one({"email": user_data["email"]})

            if existing_user:
                # Get existing cameras dictionary or create a new one
                cameras = existing_user.get("cameras", {})

                # Append to the category list, or create it if it doesn't exist
                if category not in cameras:
                    cameras[category] = []
                cameras[category].append(camera_info)

                filtered_user_data = {
                    "cameras": cameras
                }

            else:
                filtered_user_data = {
                    "name": user_data.get("name", "Unknown"),
                    "email": user_data["email"],
                    "password": self.hash_password(user_data.get("password", "defaultpassword")),
                    "role": user_data.get("role", "user"),
                    "cameras": {
                        category: [camera_info]
                    }
                }

            result = self.user_collection.update_one(
                {"email": user_data["email"]},
                {"$set": filtered_user_data},
                upsert=True
            )

            if result.upserted_id:
                logger.info(f"Created new user document for email: {user_data['email']}")
            else:
                logger.info(f"Updated existing user document for email: {user_data['email']}")

            return True

        except Exception as e:
            logger.exception("Error saving user to MongoDB")
            return False
        

    def fetch_camera_rtsp_by_email_and_category(self, email, category):
        try:
            if category not in ALLOWED_CATEGORIES:
                raise ValueError(f"Invalid category '{category}'. Allowed: {ALLOWED_CATEGORIES}")

            logger.info(f"Fetching camera details for email: {email} and category: {category}")

            user_data = self.user_collection.find_one(
                {"email": email},
                {"_id": 0, "cameras": 1}
            )

            if user_data and "cameras" in user_data:
                cameras = user_data["cameras"]
                if category in cameras:
                    logger.info(f"Camera details found for email: {email}, category: {category}")
                    return cameras[category]
                else:
                    logger.warning(f"Category '{category}' not found in cameras for email: {email}")
                    return None
            else:
                logger.warning(f"No camera details found for email: {email}")
                return None

        except Exception as e:
            logger.exception("Error fetching camera details by email and category")
            return None


    def save_snapshot_to_mongodb(self, snapshot_path, date_time, camera_id, category):
        try:
            """Saves the snapshot path, date, time, and camera_id to MongoDB in the snapshot collection."""
            print("Saving snapshot...")
            date_folder = date_time.strftime('%Y-%m-%d')
            filename = os.path.basename(snapshot_path)
            
            document = {
                'date': date_folder,
                'category': category,
                'camera_id': camera_id,
                'images': [{
                    'filename': filename,
                    'path': snapshot_path,
                    'time': date_time.strftime('%H:%M:%S')
                }] }
            
            # Update the document if the date and camera_id already exist, otherwise insert a new one
            result = self.snapshot_collection.update_one(
                {'date': date_folder, 'category': category, 'camera_id': camera_id},
                {'$push': {'images': document['images'][0]}},
                upsert=True
            )
            
            if result.upserted_id:
                print(f"Created new document for date: {date_folder} and camera_id: {camera_id}")
            else:
                print(f"Updated existing document for date: {date_folder} and camera_id: {camera_id}")
            
            print(f"Saved snapshot and metadata to MongoDB: {document}")
            logging.info(f"Sending new snapshot document to mongodb for date: {date_folder} and camera_id: {camera_id}")

        except Exception as e:
            raise Exception(e, sys) from e


    def save_video_to_mongodb(self, video_path, date_time, camera_id, category):
        try:
            """Saves the video path, date, time, and camera_id to MongoDB in the video collection."""
            print("Saving video...")
            date_folder = date_time.strftime('%Y-%m-%d')
            filename = os.path.basename(video_path)
            
            document = {
                'date': date_folder,
                'category': category,
                'camera_id': camera_id,
                'videos': [{
                    'filename': filename,
                    'path': video_path,
                    'time': date_time.strftime('%H:%M:%S') }] }
            
            # Update the document if the date and camera_id already exist, otherwise insert a new one
            result = self.video_collection.update_one(
                {'date': date_folder, 'category': category, 'camera_id': camera_id},
                {'$push': {'videos': document['videos'][0]}},
                upsert=True  )
            
            if result.upserted_id:
                print(f"Created new snapshot document for date: {date_folder} and camera_id: {camera_id}")
            else:
                print(f"Updated existing document for date: {date_folder} and camera_id: {camera_id}")
            
            print(f"Saved video and metadata to MongoDB: {document}")
            logging.info(f"Sending new video document to mongodb for date: {date_folder} and camera_id: {camera_id}")

        except Exception as e:
            raise Exception(e, sys) from e


    def fetch_snapshots_by_time_range(self, year, month, day, start_time_str, end_time_str, camera_id, category):
        try:
            date_folder = datetime(year, month, day).strftime('%Y-%m-%d')
            result = self.snapshot_collection.find_one({'date': date_folder, 'camera_id': camera_id, "category":category})

            if not result or 'images' not in result:
                logging.info(f"No snapshots found for date {date_folder}, camera_id {camera_id}")
                return []

            # Parse start and end time
            start_time = datetime.strptime(start_time_str, '%H:%M')
            end_time = datetime.strptime(end_time_str, '%H:%M')

            filtered_images = []
            for image in result['images']:
                img_time = datetime.strptime(image['time'], '%H:%M:%S')
                if start_time.time() <= img_time.time() <= end_time.time():
                    filtered_images.append(image)

            logging.info(f"Fetched {len(filtered_images)} snapshot(s) between {start_time_str} and {end_time_str} on {date_folder}")
            return filtered_images

        except Exception as e:
            raise Exception(e, sys) from e


    def fetch_snapshots_by_date_and_camera(self, year, month, day, camera_id, category):
        """Fetch snapshots from MongoDB for a specific date and camera_id."""
        try:
            date_folder = datetime(year, month, day).strftime('%Y-%m-%d')
            result = self.snapshot_collection.find_one({'date': date_folder, 'camera_id': camera_id, "category" : category})
            logging.info(f"Fetch Snapshot from MongoDB for a specific date:{year}_{month}_{day} and camera_id:{camera_id}")
            return result['images'] if result else None
        except Exception as e:
            raise Exception(e, sys) from e


    def fetch_snapshots_by_month_and_camera(self, year, month, camera_id, category):
        """Fetch snapshots from MongoDB for a specific month and camera_id."""
        try:
            start_date = datetime(year, month, 1)
            # Calculate the end date of the month
            if month < 12:
                end_date = datetime(year, month + 1, 1) - timedelta(days=1)
            else:
                end_date = datetime(year + 1, 1, 1) - timedelta(days=1)

            # Query for snapshots within the date range and specific camera_id
            results = self.snapshot_collection.find({
                'camera_id': camera_id,
                'category' : category,
                'date': {
                    '$gte': start_date.strftime('%Y-%m-%d'),
                    '$lte': end_date.strftime('%Y-%m-%d') }  })

            # Combine snapshots from all results
            snapshots = [image for result in results for image in result['images']]
            logging.info(f"Fetch Snapshot from MongoDB for a specific month:{year}_{month} and camera_id:{camera_id}")
            return snapshots if snapshots else None
        except Exception as e:
            raise Exception(e, sys) from e



















# # db_handler = MongoDBHandlerSaving()

# # user_data = {
# #     "name": "moto1",
# #     "email": "moto1",
# #     "password": "123",
# #     "role": "admin",
# #     "category": "water",  # Must be one of: fire, smoke, water, soil
# #     "cameras": [
# #         {"camera_id": "1", "rtsp": "rtsp:54/stream"},
# #         {"camera_id": "2", "rtsp": "rtsp://192.168.0.10"}
# #     ]
# # }



# # success = db_handler.save_user_to_mongodb(user_data)

# # if success:
# #     print("✅ User saved successfully!")
# # else:
# #     print("❌ Failed to save user.")



# # fetch_camera = db_handler.fetch_camera_rtsp_by_email_and_category("moto1", "water")
# # if fetch_camera:
# #     print("✅ Camera details fetched successfully!")
# #     print(fetch_camera)
# # else:
# #     print("❌ Failed to fetch camera details.")


################################################################################################################################



# user_data = {
#     "name": "Riya",
#     "email": "riya",
#     "password": "riya",
#     "role": "admin"
# }

# category = "fire"

# camera_info = {
#     "camera_id": "1",
#     "rtsp_link": "Videos/rabs1.mp4"
# }

# db_handler = MongoDBHandlerSaving()
# success = db_handler.save_user_to_mongodb(user_data, category, camera_info)

# if success:
#     print("Saved successfully!")
# else:
#     print("Something went wrong!")

# db_handler.close_connection()

# data = db_handler.fetch_camera_rtsp_by_email_and_category(email='baba', category='ppe')
# print(data)








