import logging
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import List, Optional
import os, sys
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from RabsProject.mongodb import MongoDBHandlerSaving
from RabsProject.logger import logging
from RabsProject.exception import RabsException
from RabsProject.camera_system import MultiCameraSystem, MultiCameraSystemTruck, SingleCameraSystem, SingleCameraSystemTruck
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv()

# Access the SECRET_KEY
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Password and JWT utilities
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")



####################################################################################################################
                                                ## Pydentic Models ##
####################################################################################################################



class CameraInput(BaseModel):
    camera_id: str
    rtsp_link: str
    polygonal_points:str = None

class UserInput(BaseModel):
    """User input model"""
    name: str
    email: str
    password: str
    phone_no: str
    role: str
    cameras: list[CameraInput]

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class ModelInput(BaseModel):
    model:str 

class EmailInput(BaseModel):
    email: str

class User(BaseModel):
    name: str
    email: str
    password: str
    phone_no: str
    role: str
    cameras: list
    disabled: Optional[bool] = False

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



####################################################################################################################
                                                ## Authentication Logics ##
####################################################################################################################


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



####################################################################################################################
                                                ## API Endpoints ##
####################################################################################################################



app = FastAPI()
mongo_handler = MongoDBHandlerSaving()
running_camera_systems = {}
running_single_camera_systems = {} 

app.add_middleware(
    CORSMiddleware,
    allow_origins= ["*"],  # List of domains allowed to access your API
    allow_credentials=True,  # Allows sending cookies, authorization headers
    allow_methods=["*"],     # Allows all HTTP methods: GET, POST, PUT, etc.
    allow_headers=["*", "Authorization", "Content-Type"]  # Allowed request headers
)

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
    """API to add a new user to MongoDB with properly formatted cameras."""
    try:
        # Check if user already exists
        existing_user = mongo_handler.user_collection.find_one({"email": user.email})
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")

        # Format cameras correctly
        formatted_cameras = [{"camera_id": cam.camera_id, "rtsp_link": cam.rtsp_link, "polygonal_points": cam.polygonal_points} for cam in user.cameras]

        # Prepare user data
        user_data = {
            "name": user.name,
            "email": user.email,
            "password": user.password,   
            "phone_no": user.phone_no,
            "role": user.role,
            "cameras": formatted_cameras,
            "disabled": False
        }

        # Save to MongoDB
        success = mongo_handler.save_user_to_mongodb(user_data)
        if success:
            return {"message": "User added successfully", "email": user.email}
        else:
            raise HTTPException(status_code=500, detail="Failed to add user")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/add_camera")
def add_camera(data: CameraInput,  current_user: User = Depends(get_current_user)):
    try:
        if current_user.email != current_user.email and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorized to add a camera for this user")

        existing_cameras = mongo_handler.fetch_camera_rtsp_by_email(current_user.email) or []

        # Check if camera_id already exists
        if any(cam["camera_id"] == data.camera_id for cam in existing_cameras):
            raise HTTPException(status_code=400, detail="Camera ID already exists")

        # Verify if the user has existing polygonal points
        allow_polygonal_points = mongo_handler.has_polygonal_points(email=current_user.email)

        # Construct new camera object
        new_camera = {
            "camera_id": data.camera_id,
            "rtsp_link": data.rtsp_link }

        # Only add polygonal points if the user has existing ones
        if allow_polygonal_points and data.polygonal_points:
            new_camera["polygonal_points"] = data.polygonal_points
        elif data.polygonal_points:  # If user tries to add them but they're not allowed
            raise HTTPException(status_code=400, detail="Polygonal points cannot be added for this user")

        existing_cameras.append(new_camera)

        # Save the camera using the correct function based on polygonal points
        update_status = mongo_handler.save_user_to_mongodb_truck({"email": current_user.email, "cameras": existing_cameras}) \
            if allow_polygonal_points else \
            mongo_handler.save_user_to_mongodb({"email": current_user.email, "cameras": existing_cameras})

        if update_status:
            logger.info(f"Camera {data.camera_id} added successfully for {current_user.email}")
            return {
                "message": "Camera added successfully",
                "email": current_user.email,
                "camera_id": data.camera_id,
                "rtsp_link": data.rtsp_link,
                "polygonal_points": new_camera.get("polygonal_points", "Not Allowed")  }
        else:
            raise HTTPException(status_code=500, detail="Failed to add camera")

    except Exception as e:
        raise RabsException(e, sys) from e


@app.get("/get_cameras")
def get_cameras(current_user: User = Depends(get_current_active_user)):
    if current_user.email != current_user.email and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view cameras for this user")
        
    cameras = mongo_handler.fetch_camera_rtsp_by_email(current_user.email)
    if cameras:
        return {"email": current_user.email, "cameras": cameras}
    else:
        raise HTTPException(status_code=404, detail="No cameras found for this user")


@app.delete("/remove_camera")
def remove_camera(camera_id: str, current_user: User = Depends(get_current_user)):
    try:
        """Remove a camera dynamically from the database"""
        if current_user.role != "admin" and current_user.email != current_user.email:
            raise HTTPException(status_code=403, detail="Not authorized to remove camera")

        # Ensure the camera exists before deleting
        existing_cameras = mongo_handler.fetch_camera_rtsp_by_email(current_user.email) or []
        if not any(cam["camera_id"] == camera_id for cam in existing_cameras):
            raise HTTPException(status_code=404, detail="Camera not found")

        # Use MongoDB's $pull to remove the camera directly
        result = mongo_handler.user_collection.update_one(
            {"email": current_user.email},
            {"$pull": {"cameras": {"camera_id": camera_id}}} )

        if result.modified_count > 0:
            logger.info(f"Camera {camera_id} removed successfully for {current_user.email}")
            return {"message": "Camera removed successfully", "email": current_user.email, "camera_id": camera_id}
        else:
            raise HTTPException(status_code=500, detail="Failed to remove camera")

    except Exception as e:
        raise RabsException(e, sys) from e

@app.post("/start_streaming")
async def start_streaming(model_input: ModelInput,background_tasks: BackgroundTasks,current_user: User = Depends(get_current_user)):
    try:
        """Start multi-camera streaming in a grid and return the streaming URL with embedded token"""
        global running_camera_systems

        if current_user.email in running_camera_systems:
            raise HTTPException(status_code=400, detail="Streaming is already running for this user")

        # Start the streaming system
        if mongo_handler.has_polygonal_points(email = current_user.email) == True:
            camera_system = MultiCameraSystemTruck(email=current_user.email, model_path=model_input.model)
        else:
            camera_system = MultiCameraSystem(email=current_user.email, model_path=model_input.model)

        # stream_thread = threading.Thread(target=camera_system, daemon=True)
        # stream_thread.start()

        ############ system in the background ############
        # asyncio.create_task(camera_system.start())
        background_tasks.add_task(lambda: camera_system)


        running_camera_systems[current_user.email] = camera_system
        logger.info(f"Streaming started for {current_user.email} with model {model_input.model}")

        # Create a special long-lived token for streaming
        streaming_token_expires = timedelta(hours=24)  # Adjust duration as needed
        streaming_token = create_access_token(
            data={"sub": current_user.email, "purpose": "streaming"},
            expires_delta=streaming_token_expires )

        # Generate the streaming URL with the token
        server_address = "http://0.0.0.0:8000"  # Update with your actual server address
        stream_url = f"{server_address}/stream?token={streaming_token}"
        
        return {
            "message": "Streaming started",
            "stream_url": stream_url,
            "token": streaming_token   }

    except Exception as e:
        raise RabsException(e, sys) from e

@app.get("/stream")
async def stream_video(token: str = None, authorization: str = None):
    try:
            
        """Enhanced video streaming endpoint with flexible token handling"""
        try:
            # Try to get token from query parameter first
            streaming_token = token
            
            # If no query token, try to get from Authorization header
            if not streaming_token and authorization:
                if authorization.startswith("Bearer "):
                    streaming_token = authorization.split(" ")[1]
            
            if not streaming_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="No valid token provided",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Verify token and get user
            try:
                payload = jwt.decode(streaming_token, SECRET_KEY, algorithms=[ALGORITHM])
                token_email = payload.get("sub")
                if not token_email:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid token format"
                    )
                
                # Get user from token
                user = get_user(token_email)
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="User not found" )

            except JWTError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Check if streaming is active
            if user.email not in running_camera_systems:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Streaming not found for this user"
                )
            
            camera_system = running_camera_systems[user.email]
            return StreamingResponse(
                camera_system.get_video_frames(),
                media_type="multipart/x-mixed-replace; boundary=frame"
            )

        except Exception as e:
            logger.error(f"Streaming error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Streaming error occurred"
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
                "cameras": list(system.camera_processors.keys())
            } for email, system in running_camera_systems.items()
        }
        return {"active_streams": active_streams}

    except Exception as e:
        raise RabsException(e, sys) from e

@app.post("/stop_streaming")
async def stop_streaming(current_user: User = Depends(get_current_user)):
    try:
        global running_camera_systems
        if current_user.email not in running_camera_systems:
            raise HTTPException(status_code=404, detail="No active streaming session found")
        # running_camera_systems[current_user.email].stop()
        # del running_camera_systems[current_user.email]
        camera_system = running_camera_systems.pop(current_user.email)
        await asyncio.to_thread(camera_system.stop)
        # camera_system.stop()

        logger.info(f"Streaming stopped for {current_user.email}")
        return {"message": "Streaming stopped successfully"}

    except Exception as e:
        raise RabsException(e, sys) from e


@app.post("/start_single_camera_streaming")
async def start_single_camera_streaming(camera_id: str,model_input: ModelInput,background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)):
    try:
        """Start single-camera streaming and return the streaming URL with an embedded token"""
        global running_single_camera_systems

        if current_user.email in running_single_camera_systems:
            raise HTTPException(status_code=400, detail="Streaming is already running for this user")

        if  mongo_handler.has_polygonal_points(email = current_user.email) == True:
            camera_system = SingleCameraSystemTruck(camera_id=camera_id,
                email=current_user.email, model_path= model_input.model )

        else:
            camera_system = SingleCameraSystem(camera_id=camera_id,
                email=current_user.email, model_path= model_input.model )

        # camera_system.start()
        # running_single_camera_systems[current_user.email] = camera_system

        ############ system in the background ############
        # stream_thread = threading.Thread(target=camera_system.start, daemon=True)
        # stream_thread.start()
        # asyncio.create_task(camera_system.start())
        background_tasks.add_task(camera_system.start)

         
        running_single_camera_systems[current_user.email] = camera_system
        logging.info(f"Single-camera streaming started for {current_user.email}")


        logging.info(f"Single-camera streaming started for {current_user.email}")

        # Generate a streaming token
        streaming_token_expires = timedelta(hours=24)  # Adjust duration as needed
        streaming_token = create_access_token(
            data={"sub": current_user.email, "purpose": "single_camera_streaming"},
            expires_delta=streaming_token_expires
        )

        # Generate the streaming URL with the token
        server_address = "http://0.0.0.0:8000"  # Update with your actual server address
        stream_url = f"{server_address}/single_camera_stream?token={streaming_token}"
        
        return {
            "message": "Single camera streaming started",
            "stream_url": stream_url,
            "token": streaming_token  }

    except Exception as e:
        raise RabsException(e, sys) from e


@app.get("/single_camera_stream")
async def single_camera_stream(token: str = None, authorization: str = None):
    """Video streaming endpoint for a single camera with token-based authentication"""
    try:
        # Extract token from query parameter or Authorization header
        streaming_token = token if token else authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
        
        if not streaming_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No valid token provided",
                headers={"WWW-Authenticate": "Bearer"}, )

        try:
            payload = jwt.decode(streaming_token, SECRET_KEY, algorithms=[ALGORITHM])
            token_email = payload.get("sub")
            if not token_email:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token format"  )
            
            user = get_user(token_email)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found" )

        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if streaming is active
        if user.email not in running_single_camera_systems:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Streaming not found for this user"
            )
        
        camera_system = running_single_camera_systems[user.email]
        return StreamingResponse(
            camera_system.get_video_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )

    except Exception as e:
        logging.error(f"Streaming error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Streaming error occurred"
        )

@app.post("/stop_single_camera_streaming")
async def stop_single_camera_streaming(current_user: User = Depends(get_current_user)):
    try:
        """Stop the single-camera stream for the current user"""
        global running_single_camera_systems

        if current_user.email not in running_single_camera_systems:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active streaming session found" )

        camera_system = running_single_camera_systems.pop(current_user.email)
        await asyncio.to_thread(camera_system.stop)  # Stop in a separate thread
        # camera_system.stop()
        logging.info(f"Single-camera streaming stopped for {current_user.email}")

        return {"message": "Single camera streaming stopped"}

    except Exception as e:
        raise RabsException(e, sys) from e


@app.get("/snapdate/{year}/{month}/{day}", response_model=List[SnapDate])
async def get_snapshots(year: int,  month: int, day: int, camera_id: str, current_user: User = Depends(admin_required) ):
    """Get snapshots by date for authenticated user."""
    try:
        snapshots = mongo_handler.fetch_snapshots_by_date_and_camera(year, month, day, camera_id)
        if snapshots:
            return snapshots
        raise HTTPException(status_code=404, detail="Snapshots not found for the given date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/snapmonth/{year}/{month}", response_model=List[SnapMonth])
async def get_snapshots_by_month( year: int,month: int, camera_id: str, current_user: User = Depends(admin_required) ):
    """Get snapshots by month for authenticated user."""
    try:
        snapshots = mongo_handler.fetch_snapshots_by_month_and_camera(year, month, camera_id)
        if snapshots:
            return snapshots
        raise HTTPException(status_code=404, detail="No snapshots found for the given month")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/snapdate_count-daywise/{year}/{month}/{day}", response_model=SnapshotCountResponse)
async def get_snapshots_with_count(year: int,month: int,day: int,camera_id: str, current_user: User = Depends(admin_required) ):
    """Get the count of snapshots and their details by date for authenticated user."""
    try:
        snapshots = mongo_handler.fetch_snapshots_by_date_and_camera(year, month, day, camera_id)
        if snapshots:
            return SnapshotCountResponse(count=len(snapshots), snapshots=snapshots)
        raise HTTPException(status_code=404, detail="Snapshots not found for the given date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# NEW: Fetch snapshots by HOUR
@app.get("/snapdate_timerange/{year}/{month}/{day}", response_model=List[SnapDate])
async def get_snapshots_by_time_range(year: int,month: int,day: int,start_time: str, end_time: str,camera_id: str,current_user: User = Depends(admin_required)):
    """Get snapshots between start_time and end_time on a given date."""
    try:
        snapshots = mongo_handler.fetch_snapshots_by_time_range(year, month, day, start_time, end_time, camera_id)
        if snapshots:
            return snapshots
        raise HTTPException(status_code=404, detail="Snapshots not found for given time range")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# NEW: Fetch snapshots by HOUR with COUNT
@app.get("/snapdate_count-timerange/{year}/{month}/{day}", response_model=SnapshotCountResponse)
async def get_snapshots_with_count_by_time_range(year: int, month: int, day: int, start_time: str,  end_time: str, camera_id: str, current_user: User = Depends(admin_required)): # Format: "HH:MM"
    """Get snapshot count + details for a custom time range on a given date."""
    try:
        snapshots = mongo_handler.fetch_snapshots_by_time_range(year, month, day, start_time, end_time, camera_id)
        if snapshots:
            return SnapshotCountResponse(count=len(snapshots), snapshots=snapshots)
        raise HTTPException(status_code=404, detail="Snapshots not found for given time range")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)



####################################################################################################################
                                                ## END ##
####################################################################################################################
