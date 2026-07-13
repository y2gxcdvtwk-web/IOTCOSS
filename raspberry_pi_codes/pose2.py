sudo apt update
sudo apt install python3-picamera2
pip install mediapipe opencv-python

from picamera2 import Picamera2
import cv2
import mediapipe as mp
import math
import time
import csv
from datetime import datetime

# ============================
# Configuration
# ============================

CAPTURE_INTERVAL = 300      # 5 minutes
ANGLE_WARNING = 80
ANGLE_TURTLENECK = 70

# ============================
# MediaPipe
# ============================

mp_pose = mp.solutions.pose

pose = mp_pose.Pose(
    static_image_mode=True,
    model_complexity=1,
    min_detection_confidence=0.5
)

# ============================
# Pi Camera 3
# ============================

picam2 = Picamera2()

config = picam2.create_still_configuration(
    main={"size": (1280, 720)}
)

picam2.configure(config)

picam2.start()

time.sleep(2)

# ============================
# CSV
# ============================

try:
    open("log.csv")
except:
    with open("log.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time", "Angle", "State"])

# ============================
# Functions
# ============================

def capture():

    frame = picam2.capture_array()

    if frame is None:
        return None

    return frame


def detect(frame):

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    result = pose.process(rgb)

    if not result.pose_landmarks:
        return None, None

    lm = result.pose_landmarks.landmark

    leftEar = lm[7]
    rightEar = lm[8]

    leftShoulder = lm[11]
    rightShoulder = lm[12]

    earX = (leftEar.x + rightEar.x) / 2
    earY = (leftEar.y + rightEar.y) / 2

    shoulderX = (leftShoulder.x + rightShoulder.x) / 2
    shoulderY = (leftShoulder.y + rightShoulder.y) / 2

    dx = earX - shoulderX
    dy = shoulderY - earY

    angle = math.degrees(math.atan2(dy, dx))

    if angle < ANGLE_TURTLENECK:
        state = "Turtle Neck"

    elif angle < ANGLE_WARNING:
        state = "Warning"

    else:
        state = "Normal"

    return angle, state


def save(frame, angle, state):

    now = datetime.now()

    filename = now.strftime("%Y%m%d_%H%M%S.jpg")

    cv2.imwrite(filename, frame)

    with open("log.csv", "a", newline="") as f:

        writer = csv.writer(f)

        writer.writerow([now, round(angle,2), state])


def output(angle, state):

    print("--------------------------------")
    print("Time  :", datetime.now())
    print("Angle :", round(angle,2))
    print("State :", state)
    print("--------------------------------")

    # Arduino Serial
    # serial.write(state.encode())

    # LED
    # Desk
    # LCD


# ============================
# Main
# ============================

print("===== System Started =====")

try:

    while True:

        print("Capturing image...")

        frame = capture()

        if frame is None:
            print("Capture Failed")
            time.sleep(1)
            continue

        angle, state = detect(frame)

        if angle is None:

            print("No person detected.")

        else:

            output(angle, state)

            save(frame, angle, state)

        print("Waiting 5 minutes...\n")

        time.sleep(CAPTURE_INTERVAL)

except KeyboardInterrupt:

    print("Program terminated.")

finally:

    picam2.stop()

    cv2.destroyAllWindows()