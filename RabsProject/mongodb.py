
import logging
import os, sys
from datetime import datetime, timedelta
from pymongo import MongoClient
from bcrypt import hashpw, gensalt
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv()



class MongoDBHandlerSaving:
    def __init__(self, url = os.getenv("MONGODB_URL_ACCESS"), db_name="RabsProject", user_collection_name="UserAuth", snapshot_collection_name='Snapshots', video_collection_name='Videos'):
        """Initialize the MongoDB client and select the database and collection."""
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
        """Close the MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")


    @staticmethod
    def hash_password(password):
        """Hash the user's password before storing it."""
        return hashpw(password.encode(), gensalt()).decode()


    def save_user_to_mongodb(self, user_data):
        """Insert or update user data securely with camera details."""
        try:
            # Fetch existing user data
            existing_user = self.user_collection.find_one({"email": user_data["email"]})
            
            if existing_user:
                # If user exists, only update cameras without overwriting name, role, etc.
                filtered_user_data = {"cameras": user_data.get("cameras", [])}
            else:
                # If new user, ensure required fields exist
                filtered_user_data = {
                    "name": user_data.get("name", "Unknown"),  # Default to 'Unknown' if missing
                    "email": user_data["email"],

                    "password": self.hash_password(user_data.get("password", "defaultpassword")),  

                    "phone_no": user_data.get("phone_no", ""),
                    "role": user_data.get("role", "user"),
                    "cameras": user_data.get("cameras", [])  }

            result = self.user_collection.update_one(
                {"email": user_data["email"]},  # Match existing user by email
                {"$set": filtered_user_data},  # Only update provided fields
                upsert=True  )

            if result.upserted_id:
                logger.info(f"Created new user document for email: {user_data['email']}")
            else:
                logger.info(f"Updated existing user document for email: {user_data['email']}")

            return True  

        except Exception as e:
            logger.exception("Error saving user to MongoDB")
            return False


    def save_user_to_mongodb_truck(self, user_data):
        """Insert or update user data securely with camera details, including polygonal points."""
        try:
            # Fetch existing user data
            existing_user = self.user_collection.find_one({"email": user_data["email"]})
            
            if existing_user:
                # If user exists, update cameras while preserving existing rtsp_link and adding polygonal_points
                updated_cameras = existing_user.get("cameras", [])

                new_cameras = user_data.get("cameras", [])
                for new_camera in new_cameras:
                    existing_camera = next((cam for cam in updated_cameras if cam["camera_id"] == new_camera["camera_id"]), None)
                    
                    if existing_camera:
                        # Ensure polygonal_points is stored as a proper list
                        existing_camera["polygonal_points"] = new_camera.get("polygonal_points", [])
                    else:
                        # Add new camera with proper polygonal_points format
                        updated_cameras.append({
                            "camera_id": new_camera["camera_id"],
                            "rtsp_link": new_camera.get("rtsp_link", ""),
                            "polygonal_points": new_camera.get("polygonal_points", [])
                        })

                filtered_user_data = {"cameras": updated_cameras}

            else:
                # If new user, ensure required fields exist
                filtered_user_data = {
                    "name": user_data.get("name", "Unknown"),
                    "email": user_data["email"],
                    "password": self.hash_password(user_data.get("password", "defaultpassword")),  
                    "phone_no": user_data.get("phone_no", ""),
                    "role": user_data.get("role", "user"),
                    "cameras": user_data.get("cameras", [])
                }

            result = self.user_collection.update_one(
                {"email": user_data["email"]},  # Match existing user by email
                {"$set": filtered_user_data},  # Only update provided fields
                upsert=True  # Insert if it doesn't exist
            )

            if result.upserted_id:
                logger.info(f"Created new user document for email: {user_data['email']}")
            else:
                logger.info(f"Updated existing user document for email: {user_data['email']}")

            return True  # Indicate success

        except Exception as e:
            logger.exception("Error saving user to MongoDB")
            return False

       
    def fetch_camera_rtsp_by_email(self, email):
        """Retrieve camera ID and RTSP links for a given email."""
        try:
            logger.info(f"Fetching camera details for email: {email}")

            user_data = self.user_collection.find_one(
                {"email": email}, 
                {"_id": 0, "cameras": 1}  # Fetch only cameras field
            )

            if user_data and "cameras" in user_data:
                logger.info(f"Camera details found for email: {email}: {user_data['cameras']}")
                return user_data["cameras"]
            else:
                logger.warning(f"No camera details found for email: {email}")
                return None

        except Exception as e:
            logger.exception("Error fetching camera details from MongoDB")
            return None


    def has_polygonal_points(self, email):
        """Check if any camera associated with the given email has polygonal points."""
        try:
            logger.info(f"Checking for polygonal points in cameras for email: {email}")

            # Fetch the user's camera data
            user_data = self.user_collection.find_one(
                {"email": email},
                {"_id": 0, "cameras": 1}  # Only fetch the cameras field
            )

            if user_data and "cameras" in user_data:
                for camera in user_data["cameras"]:
                    if "polygonal_points" in camera and camera["polygonal_points"]:
                        logger.info(f"Polygonal points found for email: {email}")
                        return True  # Found a camera with polygonal points

            logger.info(f"No polygonal points found for email: {email}")
            return False  # No cameras have polygonal points

        except Exception as e:
            logger.exception("Error checking polygonal points")
            return False


    def save_snapshot_to_mongodb(self, snapshot_path, date_time, camera_id):
        try:
            """Saves the snapshot path, date, time, and camera_id to MongoDB in the snapshot collection."""
            print("Saving snapshot...")
            date_folder = date_time.strftime('%Y-%m-%d')
            filename = os.path.basename(snapshot_path)
            
            document = {
                'date': date_folder,
                'camera_id': camera_id,
                'images': [{
                    'filename': filename,
                    'path': snapshot_path,
                    'time': date_time.strftime('%H:%M:%S')
                }] }
            
            # Update the document if the date and camera_id already exist, otherwise insert a new one
            result = self.snapshot_collection.update_one(
                {'date': date_folder, 'camera_id': camera_id},
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


    def save_video_to_mongodb(self, video_path, date_time, camera_id):
        try:
            """Saves the video path, date, time, and camera_id to MongoDB in the video collection."""
            print("Saving video...")
            date_folder = date_time.strftime('%Y-%m-%d')
            filename = os.path.basename(video_path)
            
            document = {
                'date': date_folder,
                'camera_id': camera_id,
                'videos': [{
                    'filename': filename,
                    'path': video_path,
                    'time': date_time.strftime('%H:%M:%S') }] }
            
            # Update the document if the date and camera_id already exist, otherwise insert a new one
            result = self.video_collection.update_one(
                {'date': date_folder, 'camera_id': camera_id},
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


    def fetch_snapshots_by_time_range(self, year, month, day, start_time_str, end_time_str, camera_id):
        """
        Fetch snapshots between a specific time range on a given date for a camera.
        Time format: 'HH:MM' (e.g., '14:15', '14:45')
        """
        try:
            date_folder = datetime(year, month, day).strftime('%Y-%m-%d')
            result = self.snapshot_collection.find_one({'date': date_folder, 'camera_id': camera_id})

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


    def fetch_snapshots_by_date_and_camera(self, year, month, day, camera_id):
        """Fetch snapshots from MongoDB for a specific date and camera_id."""
        try:
            date_folder = datetime(year, month, day).strftime('%Y-%m-%d')
            result = self.snapshot_collection.find_one({'date': date_folder, 'camera_id': camera_id})
            logging.info(f"Fetch Snapshot from MongoDB for a specific date:{year}_{month}_{day} and camera_id:{camera_id}")
            return result['images'] if result else None
        except Exception as e:
            raise Exception(e, sys) from e


    def fetch_snapshots_by_month_and_camera(self, year, month, camera_id):
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
                'date': {
                    '$gte': start_date.strftime('%Y-%m-%d'),
                    '$lte': end_date.strftime('%Y-%m-%d') }  })

            # Combine snapshots from all results
            snapshots = [image for result in results for image in result['images']]
            logging.info(f"Fetch Snapshot from MongoDB for a specific month:{year}_{month} and camera_id:{camera_id}")
            return snapshots if snapshots else None
        except Exception as e:
            raise Exception(e, sys) from e



####################################################################################################################
                                                ## Normal User ##
####################################################################################################################



# mongo_handler = MongoDBHandlerSaving()
# user_data = {
#     "name": "vnp",s
#     "email":"vnp@gmail.com",
#     "password": "vnp123",
#     "phone_no": "1234567890",
#     "role": "admin",
#     "cameras": [
#         {"camera_id": "CAMERA_1", "rtsp_link": "Videos/rabs.mp4"},
#         {"camera_id": "CAMERA_2", "rtsp_link": "Videos/rabs1.mp4"},
#     ]
# }

# mongo_handler.save_user_to_mongodb(user_data)



####################################################################################################################
                                                ## Loading and Unloading User ##
####################################################################################################################



# mongo_handler = MongoDBHandlerSaving()
# user_data = {
#     "name": "com",
#     "email": "com",
#     "password": "com",
#     "phone_no": "1234567890",
#     "role": "user",
#     "cameras": [
        # {
        #     "camera_id": "CAMERA_1",
        #     "rtsp_link": "Videos/rabs.mp4",
        #     "polygonal_points": "[(571, 716), (825, 577), (1259, 616), (1256, 798)]"
        # },
#         {
#             "camera_id": "CAMERA_2",
#             "rtsp_link": "Videos/rabs1.mp4",
#             "polygonal_points": "[(456, 6), (85, 57), (129, 616), (156, 798)]"
#         }
#     ]
# }

# mongo_handler.save_user_to_mongodb(user_data)
# camera_details = mongo_handler.fetch_camera_rtsp_by_email("alice")
# print("Camera Details:", camera_details)



####################################################################################################################
                                                ## END ##
####################################################################################################################



# mongo = MongoDBHandlerSaving()



# from datetime import datetime

# data = mongo.save_video_to_mongodb(
#     video_path="snapshots/2025-03-29/camera_CAMERA_1_12-57-36.mp4",
#     date_time=datetime.strptime("25-06-2025", "%d-%m-%Y"),
#     camera_id=100
# )



