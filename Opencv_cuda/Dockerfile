ARG CUDA="12.6.3"
ARG UBUNTU="22.04"
ARG ARCH=""

FROM nvidia/cuda${ARCH}:${CUDA}-devel-ubuntu${UBUNTU}

ARG NVIDIA_DISTRO="ubuntu2204/x86_64"
ARG OPENCV="4.10.0"
ARG CUDA_ARCH_BIN="8.9"
ARG CUDA_ARCH_PTX=""
ARG CUDNN="OFF"
ARG VIDEO_CODEC_SDK="12.2.72"
ARG VIDEO_CODEC_SDK_PATH="video_codec_sdk"

ENV DEBIAN_FRONTEND=noninteractive
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

RUN apt update && apt install -y --no-install-recommends build-essential \
    cmake \
    cmake-data \
    build-essential \
    gcc g++ \
    gdb \
    git \
    wget \
    unzip \
    yasm \
    doxygen \
    pkg-config \
    checkinstall \
    libatlas-base-dev \
    gfortran \
    libflann-dev \
    libglew-dev \
    libgdal-dev \
    libeigen3-dev \
    libgflags-dev \
    libgoogle-glog-dev \
    libprotobuf-dev \
    protobuf-compiler \
    libgtk2.0-dev \
    python3 python3-dev python3-numpy \
    libleptonica-dev \
    libtesseract-dev \
    liblapack-dev \
    libhdf5-serial-dev \
    qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools \
    libgtk-3-dev libgtk2.0-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev libtiff5-dev \
    libdc1394-dev \
    ffmpeg \
    libavcodec-dev libavformat-dev libavutil-dev libswscale-dev \
    libgstreamer1.0-0 libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev libgstreamer-plugins-bad1.0-dev \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    gir1.2-gst-rtsp-server-1.0 gstreamer1.0-rtsp gstreamer1.0-plugins-base-apps \
    libv4l-dev \
    libtbb-dev libtbb2

WORKDIR /tmp

# Copy Video Codec SDK and create symbolic link
ADD ${VIDEO_CODEC_SDK_PATH}/Video_Codec_SDK_${VIDEO_CODEC_SDK}.zip /tmp
RUN unzip Video_Codec_SDK_${VIDEO_CODEC_SDK}.zip && rm Video_Codec_SDK_${VIDEO_CODEC_SDK}.zip
RUN cp /tmp/Video_Codec_SDK_${VIDEO_CODEC_SDK}/Interface/* /usr/local/cuda/include/
# Copy libs for build image
RUN cp /tmp/Video_Codec_SDK_${VIDEO_CODEC_SDK}/Lib/linux/stubs/x86_64/* /usr/lib/x86_64-linux-gnu/ && \
    ln -s /usr/lib/x86_64-linux-gnu/libnvcuvid.so /usr/lib/x86_64-linux-gnu/libnvcuvid.so.1 && \
    ln -s /usr/lib/x86_64-linux-gnu/libnvidia-encode.so /usr/lib/x86_64-linux-gnu/libnvidia-encode.so.1 && \
    ln -s /usr/lib/x86_64-linux-gnu/libnvcuvid.so.1 /usr/local/cuda/lib64/libnvcuvid.so && \
    ln -s /usr/lib/x86_64-linux-gnu/libnvidia-encode.so.1 /usr/local/cuda/lib64/libnvidia-encode.so

RUN git clone --branch 4.10.0 https://github.com/opencv/opencv.git

RUN git clone --branch 4.10.0 https://github.com/opencv/opencv_contrib.git

RUN mkdir opencv/build && \
    cd opencv/build && \
    cmake -DCMAKE_BUILD_TYPE=RELEASE \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DCMAKE_LIBRARY_PATH=/usr/local/cuda/lib64/stubs \
        -DWITH_CUDA=ON \
        -DWITH_NVCUVID=ON \
        -DWITH_CUDNN=${CUDNN} \
        -DWITH_CUBLAS=ON \
        -DWITH_TBB=ON \
        -DWITH_GTK=ON \
        -DWITH_QT=ON \
        -DENABLE_FAST_MATH=ON \
        -DCUDA_FAST_MATH=ON \
        -DCUDA_ARCH_BIN=${CUDA_ARCH_BIN} \
        -DCUDA_ARCH_PTX=${CUDA_ARCH_PTX} \
        -DOPENCV_EXTRA_MODULES_PATH=/tmp/opencv_contrib/modules \
        -DOPENCV_DNN_CUDA=${CUDNN} \
        -DOPENCV_ENABLE_NONFREE=OFF \
        -DBUILD_TESTS=OFF \
        -DBUILD_PERF_TESTS=OFF \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_JAVA=OFF \
        -DBUILD_opencv_apps=ON \
        -DBUILD_opencv_python2=OFF \
        -DBUILD_opencv_python3=ON \
        .. && \
    make && \
    make install && \
    ldconfig


# Build the image
# docker build -t opencv-cuda .

# Check TH display
# xhost +local:docker


# Run the image
#     docker run --rm -it -p 8888:8888 --gpus all \
#   -e DISPLAY=$DISPLAY \
#   -v /tmp/.X11-unix:/tmp/.X11-unix \
#   -v /path/to/your/local/dir:/workspace \
#   opencv-cuda
