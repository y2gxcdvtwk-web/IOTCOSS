# AE이름과 container 이름만 정해지면 됨


from picamera2 import Picamera2
from ultralytics import YOLO
import cv2
import math
import time
import requests
import base64
from datetime import datetime

# ===========================
# Mobius Setting (Temporary)
# ===========================

MOBIUS_URL = "https://onem2m.iotcoss.ac.kr:7579/Mobius/SmartDesk/Camera"

HEADERS = {
    "X-M2M-Origin": "admin:admin",
    "Content-Type": "application/json;ty=4",
    "Accept": "application/json"
}

CAPTURE_INTERVAL = 300      # 5 minutes

# ===========================
# YOLO Model
# ===========================

print("Loading YOLO Model...")

model = YOLO("yolov8n-pose.pt")

# ===========================
# Camera
# ===========================

print("Initializing Camera...")

picam2 = Picamera2()

config = picam2.create_still_configuration(
    main={"size": (640,480)}
)

picam2.configure(config)

picam2.start()

time.sleep(2)

print("Camera Ready")

# ===========================
# Turtle Neck Detection
# ===========================

def detect_turtle_neck(results):

    if len(results[0].keypoints.xy)==0:
        return None,None

    kp = results[0].keypoints.xy[0]

    leftEar = kp[3]
    rightEar = kp[4]

    leftShoulder = kp[5]
    rightShoulder = kp[6]

    earX = (leftEar[0]+rightEar[0])/2
    earY = (leftEar[1]+rightEar[1])/2

    shoulderX = (leftShoulder[0]+rightShoulder[0])/2
    shoulderY = (leftShoulder[1]+rightShoulder[1])/2

    dx = earX-shoulderX
    dy = shoulderY-earY

    angle = math.degrees(math.atan2(dy,dx))

    if angle>=80:
        state="Normal"

    elif angle>=70:
        state="Warning"

    else:
        state="Turtle Neck"

    return float(angle),state

# ===========================
# Send Mobius
# ===========================

def send_to_mobius(filename,angle,state):

    with open(filename,"rb") as f:
        image=base64.b64encode(f.read()).decode()

    payload={

        "m2m:cin":{

            "con":{

                "time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

                "state":state,

                "angle":angle,

                "image":image

            }

        }

    }

    try:

        response=requests.post(

            MOBIUS_URL,

            headers=HEADERS,

            json=payload,

            timeout=20

        )

        print("Mobius :",response.status_code)

    except Exception as e:

        print(e)

# ===========================
# Main
# ===========================

print("==============================")
print(" Smart Desk Started ")
print("==============================")

frame_count=0

try:

    while True:

        frame=picam2.capture_array()

        filename=datetime.now().strftime("%Y%m%d_%H%M%S.jpg")

        cv2.imwrite(filename,frame)

        frame_count+=1

        print("--------------------------------")

        print("Capture :",frame_count)

        results=model(frame)

        angle,state=detect_turtle_neck(results)

        if angle is None:

            print("No Person Detected")

            cv2.imshow("Camera",frame)

        else:

            print("Angle :",round(angle,2))

            print("State :",state)

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
                str(round(angle,2)),
                (20,80),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0,255,255),
                2
            )

            cv2.imshow("Camera",frame)

            send_to_mobius(filename,angle,state)

        print("--------------------------------")

        if cv2.waitKey(1)&0xFF==ord('q'):
            break

        time.sleep(CAPTURE_INTERVAL)

except KeyboardInterrupt:

    print("Program End")

finally:

    picam2.stop()

    cv2.destroyAllWindows()
