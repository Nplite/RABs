import logging
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import os, sys
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from typing import List, Dict, Optional
from fastapi.staticfiles import StaticFiles
from fastapi import BackgroundTasks
from datetime import datetime, timedelta
from jose import jwt, JWTError
from typing import List, Optional, Tuple
from passlib.context import CryptContext
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
from fastapi import Query

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from RabsProject.camera_system import MultiCameraSystemSafty, SingleCameraSystemSafty, MultiCameraSystemTruck, SingleCameraSystemTruck
from RabsProject.camera_system import MultiCameraSystemFire, SingleCameraSystemFire , MultiCameraSystemSmoke, SingleCameraSystemSmoke
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
from RabsProject.mon import MongoDBHandlerSaving
from RabsProject.logger import logging
from RabsProject.exception import RabsException
logger = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv()


SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
HOSTING_LINK = os.getenv("HOSTING_LINK")
ACCESS_TOKEN_EXPIRE_MINUTES = 60


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI()
mongo_handler = MongoDBHandlerSaving()
running_camera_systems = {}
running_single_camera_systems = {}


# Serve static files (snapshots directory)
app.mount("/snapshots", StaticFiles(directory="snapshots"), name="snapshots")



####################################################################################################################
                                                ## Pydentic Models ##
####################################################################################################################



class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class ModelInput(BaseModel):
    model: str

class CameraInput(BaseModel):
    camera_id: str
    rtsp_link: str
    category: Optional[str] = None
    polygon_points: Optional[str] = None 


class User(BaseModel):
    name: str
    email: str
    password: str
    category: Optional[str] = None
    role: str
    cameras: Dict[str, List[CameraInput]]
    disabled: Optional[bool] = None

class UserInput(BaseModel):
    name: str
    email: str
    password: str
    role: str

class SnapDate(BaseModel):
    filename: str
    path: str
    time: str

class SnapMonth(BaseModel):
    filename: str
    path: str
    time: str

class SnapshotCountResponse(BaseModel):
    count: int
    snapshots: List[SnapDate]  # Replace SnapDate with your snapshot model

def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        raise RabsException(e, sys) from e

def get_password_hash(password):
    try:
        return pwd_context.hash(password)
    
    except Exception as e:
        raise RabsException(e, sys) from e

def get_user(email: str):
    try:
        user_data = mongo_handler.user_collection.find_one({"email": email}, {"_id": 0})
        if user_data:
            return User(**user_data)
        return None
    
    except Exception as e:
        raise RabsException(e, sys) from e

def authenticate_user(email: str, password: str):
    try:
        user_data = mongo_handler.user_collection.find_one({"email": email})
        
        if not user_data:
            return False

        if not verify_password(password, user_data["password"]):
            return False

        return User(**user_data)  # Convert to Pydantic Model
    
    except Exception as e:
        raise RabsException(e, sys) from e

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    try:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=15)
        to_encode.update({"exp": expire, "sub": data["sub"]})  # Ensure "sub" is always included
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    except Exception as e:
        raise RabsException(e, sys) from e

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email: str = payload.get("sub")
            if email is None:
                raise credentials_exception
        except JWTError:
            raise credentials_exception

        user = get_user(email)
        if user is None:
            raise credentials_exception
        return user
    
    except Exception as e:
        raise RabsException(e, sys) from e

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    try:
        if current_user.disabled is None:
            current_user.disabled = False  # Default to False if missing

        if current_user.disabled:
            raise HTTPException(status_code=400, detail="Inactive user")
        return current_user

    except Exception as e:
        raise RabsException(e, sys) from e

def admin_required(current_user: User = Depends(get_current_active_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access forbidden: Admins only")
    return current_user



app.add_middleware(
    CORSMiddleware,
    allow_origins= ["*"],  # List of domains allowed to access your API
    allow_credentials=True,  # Allows sending cookies, authorization headers
    allow_methods=["*"],     # Allows all HTTP methods: GET, POST, PUT, etc.
    allow_headers=["*", "Authorization", "Content-Type"]  )



@app.get("/")
def read_root():
    return {"message": "Welcome to RabsProject"}


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        user = authenticate_user(form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.email, "role":user.role}, expires_delta=access_token_expires  
        )
        return {"access_token": access_token, "token_type": "bearer"}

    except Exception as e:
        raise RabsException(e, sys) from e


@app.post("/add_new_user")
def add_user(user: UserInput):
    """API to add a new user to MongoDB (no cameras at creation)."""
    try:
        existing_user = mongo_handler.user_collection.find_one({"email": user.email})

        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists.")

        user_data = {
            "name": user.name,
            "email": user.email,
            "password": get_password_hash(user.password),  # Hash password
            "role": user.role,
            "cameras": {}  # Start with empty camera structure
        }

        result = mongo_handler.user_collection.insert_one(user_data)

        if not result.inserted_id:
            raise HTTPException(status_code=500, detail="Failed to create user.")

        return {
            "message": "User added successfully",
            "email": user.email
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# @app.post("/add_camera")
# def add_camera(data: CameraInput, current_user: User = Depends(get_current_active_user)):
#     """
#     Add a new camera under a specific category for the current user.
#     """
#     try:
#         if current_user.email != current_user.email and current_user.role != "admin":
#             raise HTTPException(status_code=403, detail="Not authorized to add a camera for this user")

#         user_data = mongo_handler.user_collection.find_one(
#             {"email": current_user.email},
#             {"_id": 0, "cameras": 1}
#         )

#         if not user_data:
#             raise HTTPException(status_code=404, detail="User not found")

#         cameras_by_category = user_data.get("cameras", {})

#         # Ensure the category exists
#         if data.category not in cameras_by_category:
#             cameras_by_category[data.category] = []

#         # Check if camera_id already exists in the specific category
#         if any(cam["camera_id"] == data.camera_id for cam in cameras_by_category[data.category]):
#             raise HTTPException(status_code=400, detail="Camera ID already exists in this category")

#         # Add the new camera to the specified category
#         new_camera = {
#             "camera_id": data.camera_id,
#             "rtsp_link": data.rtsp_link
#         }
#         cameras_by_category[data.category].append(new_camera)

#         # Update the user's cameras
#         update_result = mongo_handler.user_collection.update_one(
#             {"email": current_user.email},
#             {"$set": {"cameras": cameras_by_category}}
#         )

#         if update_result.modified_count == 0:
#             raise HTTPException(status_code=500, detail="Failed to add camera")

#         logger.info(f"Camera {data.camera_id} added successfully under category {data.category} for {current_user.email}")

#         return {
#             "message": "Camera added successfully",
#             "email": current_user.email,
#             "category": data.category,
#             "camera_id": data.camera_id,
#             "rtsp_link": data.rtsp_link
#         }

#     except Exception as e:
#         raise RabsException(e, sys) from e

# @app.post("/add_camera")
# def add_camera(data: CameraInput, current_user: User = Depends(get_current_active_user)):
#     try:
#         if not data.category:
#             raise HTTPException(status_code=400, detail="Camera category is required")

#         if data.category == "truck" and not data.polygon_points:
#             raise HTTPException(status_code=400, detail="Polygon points are required for fire category")

#         user_data = mongo_handler.user_collection.find_one(
#             {"email": current_user.email},
#             {"_id": 0, "cameras": 1}
#         )

#         if not user_data:
#             raise HTTPException(status_code=404, detail="User not found")

#         cameras_by_category = user_data.get("cameras", {})

#         if data.category not in cameras_by_category:
#             cameras_by_category[data.category] = []

#         if any(cam["camera_id"] == data.camera_id for cam in cameras_by_category[data.category]):
#             raise HTTPException(status_code=400, detail="Camera ID already exists in this category")

#         new_camera = {
#             "camera_id": data.camera_id,
#             "rtsp_link": data.rtsp_link,
#         }

#         # Only add polygon_points if category is fire
#         if data.category == "truck":
#             new_camera["polygon_points"] = data.polygon_points

#         cameras_by_category[data.category].append(new_camera)

#         update_result = mongo_handler.user_collection.update_one(
#             {"email": current_user.email},
#             {"$set": {"cameras": cameras_by_category}}
#         )

#         if update_result.modified_count == 0:
#             raise HTTPException(status_code=500, detail="Failed to add camera")

#         return {
#             "message": "Camera added successfully",
#             "email": current_user.email,
#             "category": data.category,
#             "camera_id": data.camera_id
#         }

#     except Exception as e:
#         raise RabsException(e, sys) from e

import ast

@app.post("/add_camera")
def add_camera(data: CameraInput, current_user: User = Depends(get_current_active_user)):
    try:
        if not data.category:
            raise HTTPException(status_code=400, detail="Camera category is required")

        if data.category == "truck":
            if not data.polygon_points:
                raise HTTPException(status_code=400, detail="Polygon points required for  category")
            
            try:
                # Validate that it's a proper list of tuples
                parsed_points = ast.literal_eval(data.polygon_points)
                if not isinstance(parsed_points, list) or not all(isinstance(point, tuple) and len(point) == 2 for point in parsed_points):
                    raise ValueError
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid polygon_points format. Use string like: \"[(x1, y1), (x2, y2)]\"")

        user_data = mongo_handler.user_collection.find_one(
            {"email": current_user.email},
            {"_id": 0, "cameras": 1}
        )

        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        cameras_by_category = user_data.get("cameras", {})

        if data.category not in cameras_by_category:
            cameras_by_category[data.category] = []

        if any(cam["camera_id"] == data.camera_id for cam in cameras_by_category[data.category]):
            raise HTTPException(status_code=400, detail="Camera ID already exists in this category")

        new_camera = {
            "camera_id": data.camera_id,
            "rtsp_link": data.rtsp_link
        }

        if data.category == "truck":
            new_camera["polygon_points"] = data.polygon_points  # store as string

        cameras_by_category[data.category].append(new_camera)

        update_result = mongo_handler.user_collection.update_one(
            {"email": current_user.email},
            {"$set": {"cameras": cameras_by_category}}
        )

        if update_result.modified_count == 0:
            raise HTTPException(status_code=500, detail="Failed to add camera")

        return {
            "message": "Camera added successfully",
            "email": current_user.email,
            "category": data.category,
            "camera_id": data.camera_id
        }

    except Exception as e:
        raise RabsException(e, sys) from e



@app.get("/get_cameras")
def get_cameras(current_user: User = Depends(get_current_active_user)):
    try:
        if current_user.email != current_user.email and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorized to view cameras for this user")

        user_data = mongo_handler.user_collection.find_one(
            {"email": current_user.email},
            {"_id": 0, "cameras": 1}   )

        if not user_data or "cameras" not in user_data:
            raise HTTPException(status_code=404, detail="No cameras found for this user")

        cameras_by_category = user_data["cameras"]

        return {
            "email": current_user.email,
            "cameras": cameras_by_category
        }

    except Exception as e:
        raise RabsException(e, sys) from e


@app.delete("/remove_camera")
def remove_camera(camera_id: str, category: str, current_user: User = Depends(get_current_active_user)):
    try:
        if current_user.role != "admin" and current_user.email != current_user.email:
            raise HTTPException(status_code=403, detail="Not authorized to remove camera")

        user_data = mongo_handler.user_collection.find_one(
            {"email": current_user.email},
            {"_id": 0, "cameras": 1} )

        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        cameras_by_category = user_data.get("cameras", {})

        if category not in cameras_by_category:
            raise HTTPException(status_code=404, detail=f"Category '{category}' not found")

        # Filter out the camera by camera_id
        updated_cameras = [
            cam for cam in cameras_by_category[category] if cam["camera_id"] != camera_id
        ]

        if len(updated_cameras) == len(cameras_by_category[category]):
            raise HTTPException(status_code=404, detail="Camera ID not found in the specified category")

        # Update the category with the filtered list
        cameras_by_category[category] = updated_cameras

        # If no cameras left in the category, you can optionally remove the category
        if not updated_cameras:
            del cameras_by_category[category]

        # Save back to DB
        result = mongo_handler.user_collection.update_one(
            {"email": current_user.email},
            {"$set": {"cameras": cameras_by_category}}
        )

        if result.modified_count == 0:
            raise HTTPException(status_code=500, detail="Failed to remove camera")

        logger.info(f"Camera {camera_id} removed successfully from category {category} for {current_user.email}")

        return {
            "message": "Camera removed successfully",
            "email": current_user.email,
            "category": category,
            "camera_id": camera_id
        }

    except Exception as e:
        raise RabsException(e, sys) from e


@app.post("/start_streaming")
async def start_streaming(

    background_tasks: BackgroundTasks,
    category: str = Query(..., description="Camera category to start streaming"),
    current_user: User = Depends(get_current_active_user)):
    try:
        global running_camera_systems

        unique_stream_id = f"{current_user.email}_{category}"

        if unique_stream_id in running_camera_systems:
            raise HTTPException(status_code=400, detail="Streaming is already running for this user and category")

        if category == "ppe":
            camera_system = MultiCameraSystemSafty(
                email=current_user.email,
                model_path="models/ppe.pt",
                category=category    )

        elif category == "truck":
            camera_system = MultiCameraSystemTruck(
                email=current_user.email,
                model_path="models/truck.pt",
                category=category   )

        elif category == "fire":
            camera_system = MultiCameraSystemFire(
                email=current_user.email,
                model_path="models/fire.pt",
                category=category    )
            
        elif category == "smoke":
            camera_system = MultiCameraSystemSmoke(
                email=current_user.email,
                model_path="models/smoke.pt",
                category=category   )
            
        else:
            raise HTTPException(status_code=400, detail="Invalid category")

        background_tasks.add_task(lambda: camera_system)

        running_camera_systems[unique_stream_id] = camera_system
        logger.info(f"Streaming started for {current_user.email} in category {category}")

        # Create a special long-lived token for streaming
        streaming_token_expires = timedelta(hours=24)
        streaming_token = create_access_token(
            data={"sub": current_user.email, "purpose": "streaming", "category": category},
            expires_delta=streaming_token_expires)

        # Generate the streaming URL with the token
        server_address = HOSTING_LINK #"http://192.168.3.5:8015"  # Update if necessary
        stream_url = f"{server_address}/stream?token={streaming_token}"
        
        return {
            "message": "Streaming started",
            "stream_url": stream_url,
            "token": streaming_token,
            "category": category    }

    except Exception as e:
        raise RabsException(e, sys) from e


@app.get("/stream")
async def stream_video(token: str = None, authorization: str = None):
    try:
        streaming_token = token

        if not streaming_token and authorization:
            if authorization.startswith("Bearer "):
                streaming_token = authorization.split(" ")[1]

        if not streaming_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No valid token provided",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            payload = jwt.decode(streaming_token, SECRET_KEY, algorithms=[ALGORITHM])
            token_email = payload.get("sub")
            token_category = payload.get("category")  # Get category too
           
     
            print("payload",payload)

            if not token_email or not token_category:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token format"
                )

            user = get_user(token_email)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )

        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        unique_stream_id = f"{user.email}_{token_category}"

        if unique_stream_id not in running_camera_systems:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Streaming not found for this user and category"
            )

        camera_system = running_camera_systems[unique_stream_id]

        return StreamingResponse(
            camera_system.get_video_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )

    except Exception as e:
        raise RabsException(e, sys) from e


@app.get("/running_cameras")
async def running_cameras(current_user: User = Depends(get_current_user)):
    try:
        """Check which cameras are currently streaming"""
        global running_camera_systems
        active_streams = {
            email: {
                "cameras": list(system.camera_processors.keys()),
                "count": len(system.camera_processors)
            } for email, system in running_camera_systems.items()
        }
        return {"active_streams": active_streams}

    except Exception as e:
        raise RabsException(e, sys) from e
  

@app.post("/stop_streaming")
async def stop_streaming(category: str, current_user: User = Depends(get_current_user)):
    try:
        global running_camera_systems
        key = f"{current_user.email}_{category}"

        if key not in running_camera_systems:
            raise HTTPException(status_code=404, detail="No active streaming found for this user")

        camera_system = running_camera_systems[key]
        camera_system.stop()  # Assuming this stops all camera threads/processors
        del running_camera_systems[key]

        return {"message": f"Streaming stopped for user {current_user.email} in category {category}"}

    except Exception as e:
        raise RabsException(e, sys) from e


@app.post("/start_single_camera_streaming")
async def start_single_camera_streaming(camera_id: str, background_tasks: BackgroundTasks, category: str = Query(..., description="Camera category"),
                                        current_user: User = Depends(get_current_active_user)):
    
    global running_single_camera_systems
    unique_stream_id = f"{current_user.email}_{category}"

    if unique_stream_id in running_single_camera_systems:
        raise HTTPException(status_code=400, detail="Streaming is already running for this user and category")

    if category == "ppe":
        camera_system = SingleCameraSystemSafty(
            camera_id=camera_id,
            email=current_user.email,
            model_path="models/ppe.pt",
            category=category  )
        
    elif category == "truck":
        camera_system = SingleCameraSystemTruck(
            camera_id=camera_id,
            email=current_user.email,
            model_path="models/truck.pt",
            category=category   )
        
    elif category == "fire":
        camera_system = SingleCameraSystemFire(
            camera_id=camera_id,
            email=current_user.email,
            model_path="models/fire.pt",
            category=category   )
        
    elif category == "smoke":
        camera_system = SingleCameraSystemSmoke(
            camera_id=camera_id,
            email=current_user.email,
            model_path="models/smoke.pt",
            category=category   ) 
        
    else:
        raise HTTPException(status_code=400, detail="Invalid category")

    background_tasks.add_task(camera_system.start)
    # background_tasks.add_task(lambda: camera_system)

    running_single_camera_systems[unique_stream_id] = camera_system
    logging.info(f"Single-camera streaming started for {current_user.email}")

    # Generate a streaming token
    streaming_token_expires = timedelta(hours=24)  # Adjust duration as needed
    streaming_token = create_access_token(
        data={"sub": current_user.email, "purpose": "single_camera_streaming",  "category": category},
        expires_delta=streaming_token_expires )

    # Generate the streaming URL with the token
    server_address = HOSTING_LINK  #"http://192.168.3.5:8015"  # Update with your actual server address
    stream_url = f"{server_address}/single_camera_stream?token={streaming_token}"
    
    return {
        "message": "Single camera streaming started",
        "stream_url": stream_url,
        "token": streaming_token  }


@app.get("/single_camera_stream")
async def single_camera_stream(token: str = None, authorization: str = None):

    streaming_token = token

    if not streaming_token and authorization:
        if authorization.startswith("Bearer "):
            streaming_token = authorization.split(" ")[1]

    if not streaming_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No valid token provided",
            headers={"WWW-Authenticate": "Bearer"},
        )


    try:
        payload = jwt.decode(streaming_token, SECRET_KEY, algorithms=[ALGORITHM])
        token_email = payload.get("sub")
        token_category = payload.get("category")  # Get category too
    
        print("payload",payload)

        if not token_email or not token_category:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format"
            )

        user = get_user(token_email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    unique_stream_id = f"{user.email}_{token_category}"

    if unique_stream_id not in running_single_camera_systems:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Streaming not found for this user and category"
        )

    camera_system = running_single_camera_systems[unique_stream_id]

    return StreamingResponse(
        camera_system.get_video_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.post("/stop_single_camera_streaming")
async def stop_single_camera_streaming(category: str, current_user: User = Depends(get_current_user)):
    try:
        global running_single_camera_systems
        key = f"{current_user.email}_{category}"

        if key not in running_single_camera_systems:
            raise HTTPException(status_code=404, detail="No active streaming found for this user")

        camera_system = running_single_camera_systems[key]
        camera_system.stop()  # Assuming this stops all camera threads/processors
        del running_single_camera_systems[key]

        return {"message": f"Streaming stopped for user {current_user.email} in category {category}"}

    except Exception as e:
        raise RabsException(e, sys) from e


@app.get("/snapdate_count-daywise/{year}/{month}/{day}", response_model=SnapshotCountResponse)
async def get_snapshots_with_count(year: int, month: int, day: int, camera_id: str, category: str, current_user: User = Depends(get_current_user)):
    try:
        snapshots = mongo_handler.fetch_snapshots_by_date_and_camera(year, month, day, camera_id, category)
        if snapshots:
            for snap in snapshots:
                if not snap['path'].startswith("http"):
                    snap['path'] = f"http://192.168.3.9:8015{snap['path']}"
            return SnapshotCountResponse(count=len(snapshots), snapshots=snapshots)
        raise HTTPException(status_code=404, detail="Snapshots not found for the given date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/snapdate_count-timerange/{year}/{month}/{day}", response_model=SnapshotCountResponse)
async def get_snapshots_with_count_by_time_range(
    year: int, month: int, day: int, category: str,
    start_time: str, end_time: str, camera_id: str, current_user: User = Depends(get_current_user) ):
    try:
        snapshots = mongo_handler.fetch_snapshots_by_time_range(year, month, day, start_time, end_time, camera_id, category)
        if snapshots:
            for snap in snapshots:
                if not snap['path'].startswith("http"):
                    snap['path'] = f"http://192.168.3.9:8015{snap['path']}"
            return SnapshotCountResponse(count=len(snapshots), snapshots=snapshots)
        raise HTTPException(status_code=404, detail="Snapshots not found for given time range")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/snapmonth/{year}/{month}", response_model=SnapshotCountResponse )
async def get_snapshots_by_month(year: int, month: int, camera_id: str, category: str, current_user: User = Depends(get_current_user)):
    try:
        snapshots = mongo_handler.fetch_snapshots_by_month_and_camera(year, month, camera_id, category)
        if snapshots:
            for snap in snapshots:
                if not snap['path'].startswith("http"):
                    snap['path'] = f"http://192.168.3.9:8015{snap['path']}"
            return SnapshotCountResponse(count=len(snapshots), snapshots=snapshots)
        raise HTTPException(status_code=404, detail="No snapshots found for the given month")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8015)




####################################################################################################################
                                                ## END ##
####################################################################################################################

