# Build the image
 ```
 docker build -t opencv-cuda .
 ```

## For display in docker
```
xhost +local:docker
```

## To run

```docker run --rm -it -p 8888:8888 --gpus all \
-e DISPLAY=$DISPLAY \
-v /tmp/.X11-unix:/tmp/.X11-unix \
-v /home/aiserver/Desktop/cuda_opencv:/workspace \
opencv-cuda

cd ..
cd workspace
```

# OR

```
docker run --rm -it -p 8888:8888 --gpus all \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  opencv_4.10_cuda_12.6.3
  ```

## Run with local dir mount
```
docker run --rm -it -p 8888:8888 --gpus all \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /home/wolverine/workspace:/home/workspace \
  -w /home/workspace \
  opencv_4.10_cuda_12.6.3

```
