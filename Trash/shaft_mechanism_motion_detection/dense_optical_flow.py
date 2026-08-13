import cv2
import numpy as np

# 1. Initialize camera feed (0 for default webcam, or use an RTSP stream URL)
video_source = r"D:\projct_demo\Dataset_vid_plant\WhatsApp Video9 2026-08-10 at 12.25.42 PM.mp4" 
cap = cv2.VideoCapture(video_source)

if not cap.isOpened():
    print("Error: Could not open video source.")
    exit()

# 2. Read the first frame to select the Shaft area (ROI)
ret, first_frame = cap.read()
if not ret:
    print("Error: Failed to grab initial frame.")
    exit()

print("--> ACTION REQUIRED: Select the rotating shaft area using your mouse, then press ENTER or SPACE.")
roi = cv2.selectROI("Select Shaft Region", first_frame, fromCenter=False, showCrosshair=True)
cv2.destroyWindow("Select Shaft Region")

# Crop coordinates: (x, y, width, height)
x, y, w, h = int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])

# Fallback to full frame if no ROI is selected
if w == 0 or h == 0:
    x, y, w, h = 0, 0, first_frame.shape[1], first_frame.shape[0]

# 3. Preprocess the initial frame segment
prev_roi = first_frame[y:y+h, x:x+w]
prev_gray = cv2.cvtColor(prev_roi, cv2.COLOR_BGR2GRAY)

# --- CONFIGURATION TUNING ---
# Minimum average pixel velocity to consider the machine "ACTIVE"
# Increase this value if factory floor vibrations cause false positives
VELOCITY_THRESHOLD = 0.5  

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # Crop frame strictly to the shaft region
    roi_frame = frame[y:y+h, x:x+w]
    gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)

    # Calculate Dense Optical Flow using Gunnar Farneback's algorithm
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, gray, None, 
        pyr_scale=0.5, levels=3, winsize=15, 
        iterations=3, poly_n=5, poly_sigma=1.2, flags=0
    )

    # Extract horizontal (dx) and vertical (dy) displacement vectors
    dx = flow[..., 0]
    dy = flow[..., 1]

    # Compute the magnitude (velocity) of movement for each pixel
    magnitude, angle = cv2.cartToPolar(dx, dy)

    # Calculate the average movement velocity across the entire shaft ROI
    avg_velocity = np.mean(magnitude)

    # Determine Machine Status
    if avg_velocity > VELOCITY_THRESHOLD:
        status = "ACTIVE"
        color = (0, 255, 0)  # Green
    else:
        status = "STOPPED"
        color = (0, 0, 255)  # Red

    # Update the reference frame for the next iteration
    prev_gray = gray.copy()

    # --- VISUALIZATION ---
    # Draw boundary box and status on the primary display frame
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    cv2.putText(frame, f"Machine Status: {status}", (20, 50), 
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
    cv2.putText(frame, f"Avg Velocity: {avg_velocity:.3f} px/frame", (20, 90), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

    # Display the final output
    cv2.imshow("Optical Flow Shaft Monitor", frame)

    # Press 'q' to break the loop and exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
