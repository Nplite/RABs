import cv2
import numpy as np

def process_multiple_videos(video_paths):
    video_readers = []
    current_frame_numbers = []
    prev_frames = []

    for video_path in video_paths:
        try:
            video_reader = cv2.cudacodec.createVideoReader(video_path)
            video_readers.append(video_reader)
            current_frame_numbers.append(0)
            prev_frames.append(None)
            print(f"Video {len(video_readers)} initialized with CUDA decoder")
        except cv2.error as e:
            print(f"Could not open video: {video_path}")
            print(f"Error: {str(e)}")
            continue

    if not video_readers:
        print("No videos could be opened. Exiting...")
        return

    # Create CUDA streams for parallel processing
    streams = [cv2.cuda.Stream() for _ in video_readers]
    
    # Create CUDA filter for Gaussian blur
    gaussian_filter = cv2.cuda.createGaussianFilter(
        cv2.CV_8UC3, cv2.CV_8UC3, (15, 15), 0
    )
    
    try:
        while True:
            all_videos_done = True
            
            for i, (video_reader, stream) in enumerate(zip(video_readers, streams)):
                retval, gpu_frame = video_reader.nextFrame()
                
                if retval:
                    all_videos_done = False
                    
                    # Convert BGRA to BGR using CUDA
                    if gpu_frame.channels() == 4:
                        # Create BGR GpuMat
                        gpu_bgr = cv2.cuda.GpuMat(gpu_frame.size(), cv2.CV_8UC3)
                        
                        # Convert BGRA to BGR
                        cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGRA2BGR, gpu_bgr, stream=stream)
                        gpu_frame = gpu_bgr
                    
                    # Now convert BGR to grayscale
                    gpu_gray = cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGR2GRAY, stream=stream)
                    
                    # Motion detection using CUDA operations
                    if prev_frames[i] is not None:
                        # Use CUDA absdiff
                        gpu_diff = cv2.cuda.absdiff(gpu_gray, prev_frames[i], stream=stream)
                        
                        # Use CUDA threshold
                        gpu_thresh = cv2.cuda.threshold(
                            gpu_diff, 
                            25, 
                            255, 
                            cv2.THRESH_BINARY,
                            stream=stream
                        )[1]
                        
                        # Download threshold result
                        thresh_host = gpu_thresh.download(stream=stream)
                        
                        if np.sum(thresh_host) > 0:
                            # Apply Gaussian blur using CUDA filter
                            gpu_frame = gaussian_filter.apply(gpu_frame, stream=stream)
                    
                    # Update previous frame (keep on GPU)
                    prev_frames[i] = gpu_gray
                    
                    # Download and display
                    frame = gpu_frame.download(stream=stream)
                    cv2.imshow(f'Video {i + 1}', frame)
                    
                    current_frame_numbers[i] += 1
                else:
                    print(f"End of video {i + 1} or error occurred")
                    video_readers[i] = None

            if all(reader is None for reader in video_readers):
                print("All videos finished processing")
                break

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("User requested exit")
                break

    except KeyboardInterrupt:
        print("Processing interrupted by user")
    
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        cv2.destroyAllWindows()
        cv2.cuda.resetDevice()

if __name__ == "__main__":
    video_paths = [
        'rtsp://192.168.1.10:8080/h264_ulaw.sdp',
        'rtsp://192.168.1.10:8080/h264_ulaw.sdp',
        'rtsp://192.168.1.10:8080/h264_ulaw.sdp',
        'rtsp://192.168.1.10:8080/h264_ulaw.sdp',
        'rtsp://192.168.1.10:8080/h264_ulaw.sdp',
        'rtsp://192.168.1.10:8080/h264_ulaw.sdp',
        
    ]

    process_multiple_videos(video_paths)