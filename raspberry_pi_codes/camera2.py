# AE이름과 container 이름만 정해지면 됨


from picamera2 import Picamera2
from ultralytics import YOLO
import cv2
import math
import time
import requests
import base64
import os
from datetime import datetime

# ============================================
# Configuration
# ============================================

CAPTURE_INTERVAL = 300          # 5 minutes
IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480

# Turtle Neck Threshold (Example)
NORMAL_THRESHOLD = 80
WARNING_THRESHOLD = 70

# ============================================
# Mobius (Temporary)
# ============================================

MOBIUS_URL = "https://onem2m.iotcoss.ac.kr:7579/Mobius/SmartDesk/Camera"

HEADERS = {
    "X-M2M-Origin": "admin:admin",
    "Content-Type": "application/json;ty=4",
    "Accept": "application/json"
}

# ============================================
# Load YOLO11 Pose
# ============================================

print("Loading YOLO11 Pose Model...")

model = YOLO("yolo11n-pose.pt")

print("YOLO Loaded")

# ============================================
# Camera Initialize
# ============================================

print("Initializing Camera...")

picam2 = Picamera2()

config = picam2.create_still_configuration(
    main={
        "size": (IMAGE_WIDTH, IMAGE_HEIGHT)
    }
)

picam2.configure(config)

picam2.start()

time.sleep(2)

print("Camera Ready")

# ============================================
# Save Image
# ============================================

def save_image(frame):

    filename = datetime.now().strftime("%Y%m%d_%H%M%S.jpg")

    cv2.imwrite(filename, frame)

    return filename

# ============================================
# Detect Turtle Neck
# Camera : Right Side
# ============================================

def detect_turtle_neck(results):

    if results[0].keypoints is None:
        return None

    if len(results[0].keypoints.xy) == 0:
        return None

    kp = results[0].keypoints.xy[0]

    # Right Ear
    rightEar = kp[4]

    # Right Shoulder
    rightShoulder = kp[6]

    x1 = float(rightEar[0])
    y1 = float(rightEar[1])

    x2 = float(rightShoulder[0])
    y2 = float(rightShoulder[1])

    dx = x1 - x2
    dy = y2 - y1

    angle = math.degrees(math.atan2(dy, dx))

    if angle >= NORMAL_THRESHOLD:

        state = "Normal"

    elif angle >= WARNING_THRESHOLD:

        state = "Warning"

    else:

        state = "Turtle Neck"

    return {

        "angle": round(angle,2),

        "state": state,

        "ear": (int(x1), int(y1)),

        "shoulder": (int(x2), int(y2))

    }

# ============================================
# Draw Result
# ============================================

def draw_result(frame, result):

    ear = result["ear"]

    shoulder = result["shoulder"]

    angle = result["angle"]

    state = result["state"]

    cv2.circle(frame, ear, 8, (0,255,0), -1)

    cv2.circle(frame, shoulder, 8, (0,255,0), -1)

    cv2.line(frame, ear, shoulder, (255,0,0), 2)

    cv2.putText(

        frame,

        state,

        (20,40),

        cv2.FONT_HERSHEY_SIMPLEX,

        1,

        (0,255,0),

        2

    )

    cv2.putText(

        frame,

        "Angle : " + str(angle),

        (20,80),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.8,

        (0,255,255),

        2

    )

    cv2.putText(

        frame,

        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

        (20,120),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.6,

        (255,255,255),

        2

    )

# ============================================
# Send Image to Mobius
# ============================================

def send_to_mobius(filename, result):

    with open(filename, "rb") as f:

        image = base64.b64encode(f.read()).decode("utf-8")

    payload = {

        "m2m:cin":{

            "con":{

                "time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

                "state":result["state"],

                "angle":result["angle"],

                "image":image

            }

        }

    }

    try:

        response = requests.post(

            MOBIUS_URL,

            headers=HEADERS,

            json=payload,

            timeout=20

        )

        print("Mobius Status :", response.status_code)

    except Exception as e:

        print("Mobius Error :", e)

# ============================================
# Log
# ============================================

def print_result(result):

    print("------------------------------------")

    print("Time :", datetime.now())

    print("Angle :", result["angle"])

    print("State :", result["state"])

    print("------------------------------------")

# ============================================
# Main
# ============================================

print("")
print("========================================")
print(" Smart Desk System Started ")
print("========================================")
print("")

capture_count = 0

try:

    while True:

        print("Capturing image...")

        # Capture Frame
        frame = picam2.capture_array()

        if frame is None:

            print("Capture Failed")

            time.sleep(1)

            continue

        # Save Image
        filename = save_image(frame)

        capture_count += 1

        print("Capture Count :", capture_count)

        # ====================================
        # YOLO11 Pose
        # ====================================

        results = model(

            frame,

            classes=0,

            verbose=False

        )

        # ====================================
        # Turtle Neck Detection
        # ====================================

        result = detect_turtle_neck(results)

        if result is None:

            print("No Person Detected")

            cv2.imshow("Smart Desk", frame)

        else:

            print_result(result)

            draw_result(frame, result)

            cv2.imshow("Smart Desk", frame)

            print("Sending Image To Mobius...")

            send_to_mobius(

                filename,

                result

            )

            print("Upload Complete")

        print("")

        print("Waiting 5 Minutes...")

        print("")

        # q key
        key = cv2.waitKey(1)

        if key == ord('q'):

            break

        # Wait
        time.sleep(CAPTURE_INTERVAL)

except KeyboardInterrupt:

    print("")
    print("Keyboard Interrupt")
    print("")

except Exception as e:

    print("")
    print("Unexpected Error")
    print(e)
    print("")

finally:

    print("")
    print("System Shutdown")
    print("")

    picam2.stop()

    cv2.destroyAllWindows()