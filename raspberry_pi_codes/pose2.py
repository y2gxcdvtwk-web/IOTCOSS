import cv2
import mediapipe as mp
import math
import time
import csv
from datetime import datetime

# ===== Configuration =====
CAPTURE_INTERVAL = 300      # 5 minutes
ANGLE_WARNING = 80
ANGLE_TURTLENECK = 70

# ===== MediaPipe =====
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=True,
    min_detection_confidence=0.5
)

# ===== Camera =====
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Camera connection failed.")
    exit()

# ===== Create CSV =====
with open("log.csv", "a", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Time", "Angle", "State"])

def capture():
    ret, frame = cap.read()

    if not ret:
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
        writer.writerow([now, angle, state])


def output(angle, state):

    print("--------------------------------")
    print("Time  :", datetime.now())
    print("Angle :", round(angle, 2))
    print("State :", state)
    print("--------------------------------")

    # TODO: Send result to Arduino
    # TODO: Control LED
    # TODO: Control Desk
    # TODO: Display on LCD


print("===== System Started =====")

while True:

    frame = capture()

    if frame is None:
        print("Image capture failed.")
        continue

    angle, state = detect(frame)

    if angle is None:
        print("No person detected.")

    else:
        output(angle, state)
        save(frame, angle, state)

    print("Waiting for next capture (5 minutes)...")
    time.sleep(CAPTURE_INTERVAL)