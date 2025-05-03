# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . /app

# Install Python dependencies
# RUN pip install --no-cache-dir --upgrade pip \
#     && pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --upgrade pip --timeout 100 \
    && pip install --no-cache-dir --timeout 100 -r requirements.txt


# Expose FastAPI default port
EXPOSE 8015

# Command to run the application
CMD ["uvicorn", "safty:app", "--host", "0.0.0.0", "--port", "8015"]













# """

# docker ps -a                                                                       # List all containers
# docker images                                                                      # List all images
# docker ps                                                                          # List running containers
# docker volume create rabs-volume                                                   # Create volume
# docker run -d -p 8015:8015 --name rabs-container --network bridge -v rabs-volume:/app/data rabs-app                          # Run container with volume mapping
# docker build -t rabs-app .                                                         # Build image
# docker run -d -p 8015:8015 --name rabs-container --network bridge rabs-app         # Run container
# docker logs rabs-container                                                         # Check logs
# docker stop rabs-container                                                         # Stop container
# docker start rabs-container                                                        # Start container
# docker rm rabs-container                                                           # Remove container
# docker rmi rabs-app                                                                # Remove image
# docker exec -it rabs-container bash                                                # Access container
# docker cp rabs-container:/app/data/ ./data                                         # Copy data from container
# docker cp ./data rabs-container:/app/data/                                         # Copy data to container
# docker exec -it rabs-container bash                                                # Access container
# docker-compose up                                                                  # Run docker-compose
# docker-compose down                                                                # Stop docker-compose
# docker-compose up --build                                                          # Rebuild docker-compose

# """




#  docker tag rabs-app punit084/rabs:latest
#  docker push punit084/rabs:latest


