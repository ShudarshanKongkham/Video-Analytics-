import time
import numpy as np
import torch
import cv2
from models.common import DetectMultiBackend
from utils.general import check_img_size, non_max_suppression, scale_boxes
from utils.plots import Annotator, colors
from utils.torch_utils import select_device
from deep_sort_realtime.deepsort_tracker import DeepSort

def load_model(weights, device):
    """Load the YOLO model with specified weights and device."""
    device = select_device(device)  # Select GPU or CPU
    model = DetectMultiBackend(weights, device=device, fp16=True)  # Enable FP16 for GPU if supported
    return model, model.names

def resize_and_pad(image, stride=32):
    """Resize and pad the image to be compatible with the model's stride."""
    h, w = image.shape[:2]
    new_h = (h + stride - 1) // stride * stride
    new_w = (w + stride - 1) // stride * stride
    padded_image = np.zeros((new_h, new_w, 3), dtype=np.uint8)
    padded_image[:h, :w, :] = image
    return padded_image

def inference(image, model, names, deepsort, line_thickness=2):
    """Perform inference and return annotated image and detections."""
    start_time = time.time()  # Track inference time for FPS calculation

    # Resize and pad image to be stride-compatible
    padded_image = resize_and_pad(image, stride=model.stride)

    # Prepare image for inference
    img = padded_image[..., ::-1].transpose(2, 0, 1)  # BGR to RGB, 3xHxW
    img = np.ascontiguousarray(img)
    img = torch.from_numpy(img).to(model.device).float() / 255.0
    if model.fp16:  # Use half precision if available
        img = img.half()
    if img.ndimension() == 3:
        img = img.unsqueeze(0)  # Add batch dimension

    # Run inference
    pred = model(img)[0]
    pred = non_max_suppression(pred, conf_thres=0.3, iou_thres=0.45, max_det=100)

    # Initialize annotator
    im0 = image.copy()
    annotator = Annotator(im0, line_width=line_thickness, example=str(names))

    # Process detections
    detections = []
    if len(pred[0]):
        det = pred[0]
        det[:, :4] = scale_boxes(img.shape[2:], det[:, :4], im0.shape).round()

        for *xyxy, conf, cls in reversed(det):
            x1, y1, x2, y2 = map(int, xyxy)
            cls_name = names[int(cls)]  # Class name from dictionary
            detections.append(([x1, y1, x2 - x1, y2 - y1], conf.item(), cls_name))

    # Update tracker
    tracks = deepsort.update_tracks(detections, frame=im0)

    # Annotate tracked objects
    for track in tracks:
        if not track.is_confirmed() or track.time_since_update > 0:
            continue

        track_id = track.track_id
        track_cls = track.det_class

        # Reverse dictionary lookup to find the class index
        cls_index = next((k for k, v in names.items() if v == track_cls), 0)

        bbox = track.to_ltrb()  # left, top, right, bottom

        # Assign a unique color to each class using the correct index
        cls_color = colors(cls_index, True)

        # Clean and readable annotations
        label = f'ID: {track_id} | {track_cls}'
        annotator.box_label(bbox, label, color=cls_color)

    # Calculate FPS
    fps = 1 / (time.time() - start_time)
    cv2.putText(im0, f'FPS: {fps:.2f}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    return annotator.result()


def run(weights, device, output_path='output.avi'):
    """Run real-time object detection and tracking using video input."""
    model, names = load_model(weights, device)
    cap = cv2.VideoCapture("G:/UTS/2024/Spring_2024/Image Processing/Assignment/Video-Analytics-/MOT_Evaluation/data/MOT16-13/MOT16-13-raw.webm")

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    # Initialize video writer to save the output
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)  # Use the input video's FPS
    fourcc = cv2.VideoWriter_fourcc(*'XVID')  # Codec for .avi format
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    # Initialize DeepSORT tracker
    deepsort = DeepSort(
        max_age=30, n_init=3, nms_max_overlap=1.0,
        max_cosine_distance=0.7, nn_budget=None,
        embedder_gpu=True, half=True
    )

    while True:
        ret, frame = cap.read()
        if not ret:
            print("End of video or error reading frame.")
            break

        # Perform inference and display the result
        annotated_frame = inference(frame, model, names, deepsort)

        # Write the annotated frame to the output video
        out.write(annotated_frame)

        # Display the annotated frame
        cv2.imshow('YOLOv9 with DeepSORT', annotated_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Cleanup
    cap.release()
    out.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    weights = 'yolov9-c.pt'  # Path to model weights
    device = 0  # Use GPU (0) or CPU ('cpu')
    run(weights, device)
