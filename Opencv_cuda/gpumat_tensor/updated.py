import json
import cv2
from ultralytics import YOLO
import torch
from utils.memory_repr_pytorch import opencv_gpu_mat_as_pytorch_tensor


def load_config(json_path):
    with open(json_path, "r") as f:
        return json.load(f)


def create_roi_mask_gpu(frame_shape, roi_coords):
    x1, x2, y1, y2 = roi_coords
    gpu_mask = cv2.cuda_GpuMat(frame_shape[:2], cv2.CV_8UC1)
    gpu_mask.setTo(0)
    roi_region = gpu_mask.rowRange(y1, y2).colRange(x1, x2)
    roi_region.setTo(255)
    return gpu_mask


def initialize_video_streams(config):
    """
    Initialize video readers, ROI masks, and other GPU-based configurations for each video stream.
    """
    params = cv2.cudacodec.VideoReaderInitParams()
    params.targetSz = (640, 640)
    params.minNumDecodeSurfaces = 60
    params.allowFrameDrop = False
    video_streams = []

    for stream_config in config:
        try:
            uri = stream_config["uri"]
            roi_coords = stream_config["roi"]

            reader = cv2.cudacodec.createVideoReader(uri, params=params)
            reader.set(cv2.cudacodec.COLOR_FORMAT_BGR)

            gpu_mask = create_roi_mask_gpu((640, 640), roi_coords)
            
            # Pre-allocate all GPU matrices including prev_frame
            gpu_gray = cv2.cuda_GpuMat(640, 640, cv2.CV_8UC1)
            gpu_diff = cv2.cuda_GpuMat(640, 640, cv2.CV_8UC1)
            gpu_diff_roi = cv2.cuda_GpuMat(640, 640, cv2.CV_8UC1)
            gpu_thresh = cv2.cuda_GpuMat(640, 640, cv2.CV_8UC1)
            prev_frame = cv2.cuda_GpuMat(640, 640, cv2.CV_8UC1)  # Properly initialize prev_frame

            video_streams.append({
                "reader": reader,
                "roi_mask": gpu_mask,
                "prev_frame": prev_frame,
                "frame_count": 0,
                "gpu_gray": gpu_gray,
                "gpu_diff": gpu_diff,
                "gpu_diff_roi": gpu_diff_roi,
                "gpu_thresh": gpu_thresh,
                "is_first_frame": True  # Add flag to handle first frame
            })

            print(f"Successfully initialized reader for {uri}")
        except cv2.error as e:
            print(f"Failed to open {uri}: {str(e)}")

    return video_streams

def process_stream(stream, model, config, cuda_stream, stream_index):
    """
    Process a single video stream for motion detection and YOLO inference.
    """
    stream["frame_count"] += 1

    ret, gpu_frame = stream["reader"].nextFrame()
    if not ret:
        return False

    # Step 1: Apply Gaussian Blur in the ROI
    x1, x2, y1, y2 = config["roi"]
    gpu_roi = gpu_frame.rowRange(y1, y2).colRange(x1, x2)

    gaussian_filter = cv2.cuda.createGaussianFilter(cv2.CV_8UC3, cv2.CV_8UC3, (7, 7), 0)
    gpu_blurred = gaussian_filter.apply(gpu_roi, stream=cuda_stream)
    gpu_blurred.copyTo(gpu_frame.rowRange(y1, y2).colRange(x1, x2))

    # Convert frame to grayscale
    cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGR2GRAY, stream["gpu_gray"], stream=cuda_stream)

    has_motion = False
    if not stream["is_first_frame"]:
        # Perform frame differencing and motion detection
        cv2.cuda.absdiff(stream["gpu_gray"], stream["prev_frame"], stream["gpu_diff"], stream=cuda_stream)
        
        # Mask the difference using the ROI mask
        cv2.cuda.multiply(stream["gpu_diff"], stream["roi_mask"], stream["gpu_diff_roi"], 1.0/255.0, stream=cuda_stream)
        
        # Apply threshold to detect significant motion
        threshold_value = 25  # Increased threshold for better detection
        cv2.cuda.threshold(stream["gpu_diff_roi"], threshold_value, 255, cv2.THRESH_BINARY, stream["gpu_thresh"], stream=cuda_stream)
        
        # Count non-zero pixels to determine if motion has occurred
        non_zero_pixels = cv2.cuda.countNonZero(stream["gpu_thresh"])
        motion_threshold = 100  # Minimum number of changed pixels to consider as motion
        has_motion = non_zero_pixels > motion_threshold

        if has_motion:
            print(f"Motion detected in stream {stream_index + 1}! Changed pixels: {non_zero_pixels}")

    # Update the previous frame for future motion detection
    stream["gpu_gray"].copyTo(stream["prev_frame"])
    stream["is_first_frame"] = False

    # Rest of the processing (YOLO detection and display) remains the same...
    tensor_frame = opencv_gpu_mat_as_pytorch_tensor(gpu_frame)
    tensor_frame = tensor_frame.to(device="cuda", dtype=torch.float32) / 255.0
    tensor_frame = tensor_frame.permute(2, 0, 1).unsqueeze(0).contiguous()

    results = model.predict(source=tensor_frame, batch=11, device=0, verbose=False)
    frame_with_predictions = results[0].plot()
    cv2.imshow(f"Stream {stream_index + 1} - {config['uri']}", frame_with_predictions)

    cuda_stream.waitForCompletion()

    if cv2.waitKey(1) & 0xFF == ord('q'):
        return False

    return True


def process_multiple_streams(config, model):
    streams = initialize_video_streams(config)
    if not streams:
        print("No valid streams available.")
        return

    cuda_streams = [cv2.cuda.Stream() for _ in streams]

    try:
        while True:
            all_done = True
            for i, stream in enumerate(streams):
                if process_stream(stream, model, config[i], cuda_streams[i], i):
                    all_done = False

            if all_done:
                print("All streams finished.")
                break

    except KeyboardInterrupt:
        print("Processing interrupted by user.")

    finally:
        for stream in streams:
            del stream["reader"]
            # Collect keys to delete
            keys_to_delete = [key for key, value in stream.items() if isinstance(value, cv2.cuda_GpuMat)]
            for key in keys_to_delete:
                del stream[key]
        cv2.destroyAllWindows()
        torch.cuda.empty_cache()
        cv2.cuda.resetDevice()



if __name__ == "__main__":
    config_path = "gpumat_tensor/input.json"
    config = load_config(config_path)
    tensorrt_model = YOLO("yolov8n.engine")
    process_multiple_streams(config, tensorrt_model)
