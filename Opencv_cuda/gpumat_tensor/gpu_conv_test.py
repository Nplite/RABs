import cv2
from ultralytics import YOLO
import torch.cuda
from utils.memory_repr_pytorch import opencv_gpu_mat_as_pytorch_tensor


params = cv2.cudacodec.VideoReaderInitParams()
params.targetSz = (640, 640)
params.minNumDecodeSurfaces = 4

tensorrt_model = YOLO("yolov8n.engine")

video_reader = cv2.cudacodec.createVideoReader('rtsp://192.168.3.15:8080/h264_ulaw.sdp', params=params)
video_reader.set(cv2.cudacodec.COLOR_FORMAT_BGR)

while True:
    ret, gpu_frame = video_reader.nextFrame()
    if not ret:
        break
    
    try:
        # Convert GPU frame to PyTorch tensor
        tensor_frame = opencv_gpu_mat_as_pytorch_tensor(gpu_frame)
        
        # Convert to float32 and normalize BEFORE any other operations
        tensor_frame = tensor_frame.to(dtype=torch.float32)
        tensor_frame = tensor_frame / 255.0
        tensor_frame = tensor_frame.permute(2, 0, 1)  # HWC to CHW
        tensor_frame = tensor_frame.unsqueeze(0)  # Add batch dimension
        
        # Ensure we're on the correct device
        tensor_frame = tensor_frame.contiguous()
        
        # Run inference
        results = tensorrt_model.predict(
            source=tensor_frame,
            device=0,
            verbose=True
        )
        
        frame_with_predictions = results[0].plot(im_gpu='Tensor')
        
        # Convert to numpy for display
        if isinstance(frame_with_predictions, torch.Tensor):
            frame_with_predictions = frame_with_predictions.permute(1, 2, 0).cpu().numpy()
        
        cv2.imshow('Frame', frame_with_predictions)
        
    except Exception as e:
        print(f"Error in processing: {str(e)}")
        break
        
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()