import cv2
import json
import time
from datetime import datetime

from picamera2 import Picamera2
from ultralytics import YOLO


# =========================
# 설정
# =========================

IMAGE_PATH = "temp.jpg"
LOG_PATH = "posture_log.jsonl"

MODEL_PATH = "yolo11n-pose.pt"

CAPTURE_INTERVAL = 1.5   # 약 0.6 FPS


# =========================
# YOLO 모델
# =========================

print("[INFO] Loading YOLO Pose model...")
model = YOLO(MODEL_PATH)

print("[INFO] Model loaded")


# =========================
# Camera
# =========================

print("[INFO] Starting camera...")

picam2 = Picamera2()

config = picam2.create_still_configuration(
    main={
        "size": (640,480),
        "format": "RGB888"
    }
)

picam2.configure(config)

picam2.start()

time.sleep(2)

print("[INFO] Camera ready")


# =========================
# Keypoint 정의
# YOLO COCO 17개
# =========================

KEYPOINT = {
    "nose":0,

    "left_shoulder":5,
    "right_shoulder":6,

    "left_elbow":7,
    "right_elbow":8,

    "left_wrist":9,
    "right_wrist":10,

    "left_hip":11,
    "right_hip":12
}



# =========================
# 자세 분석 함수
# =========================

def calculate_posture(points):

    """
    points:
    {
        nose:[x,y,c],
        shoulder...
    }
    """

    score = 100

    result = {
        "neck_forward":False,
        "back_bent":False,
        "score":100
    }


    try:

        nose = points["nose"]

        ls = points["left_shoulder"]
        rs = points["right_shoulder"]

        lh = points["left_hip"]
        rh = points["right_hip"]


        # -------------------------
        # 어깨 중심
        # -------------------------

        shoulder_x = (
            ls[0]+rs[0]
        )/2

        shoulder_y = (
            ls[1]+rs[1]
        )/2


        # -------------------------
        # 거북목 판단
        #
        # 얼굴이 어깨보다 앞으로
        # 나와 있는지
        # -------------------------

        neck_distance = abs(
            nose[0]-shoulder_x
        )


        if neck_distance > 35:

            result["neck_forward"] = True

            score -= 25



        # -------------------------
        # 허리 굽음 판단
        #
        # 어깨-허리 수직 관계
        # -------------------------


        hip_x = (
            lh[0]+rh[0]
        )/2

        body_angle = abs(
            shoulder_x-hip_x
        )


        if body_angle > 40:

            result["back_bent"] = True

            score -= 25



        if score < 0:
            score = 0


        result["score"] = score


    except Exception as e:

        print(
            "[WARN] posture error:",
            e
        )



    return result



# =========================
# JSON 저장
# =========================

def save_log(data):

    with open(
        LOG_PATH,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            json.dumps(
                data,
                ensure_ascii=False
            )
            + "\n"
        )



# =========================
# YOLO 결과 처리
# =========================

def extract_upper_body(result):

    points={}


    if result.keypoints is None:
        return points


    xy = result.keypoints.xy.cpu().numpy()

    conf = result.keypoints.conf.cpu().numpy()


    # 사람 1명 기준
    xy = xy[0]
    conf = conf[0]


    for name,idx in KEYPOINT.items():

        points[name]=[
            float(xy[idx][0]),
            float(xy[idx][1]),
            float(conf[idx])
        ]


    return points



# =========================
# Main Loop
# =========================


print("[INFO] Start posture monitoring")


try:

    while True:


        # -------------------------
        # 촬영
        # -------------------------

        frame = picam2.capture_array()


        cv2.imwrite(
            IMAGE_PATH,
            cv2.cvtColor(
                frame,
                cv2.COLOR_RGB2BGR
            )
        )


        # -------------------------
        # YOLO
        # -------------------------

        results = model(
            IMAGE_PATH,
            verbose=False
        )


        if len(results)==0:

            time.sleep(
                CAPTURE_INTERVAL
            )

            continue



        keypoints = extract_upper_body(
            results[0]
        )


        if len(keypoints)==0:

            print(
                "No person detected"
            )

            time.sleep(
                CAPTURE_INTERVAL
            )

            continue



        # -------------------------
        # 자세 평가
        # -------------------------

        posture = calculate_posture(
            keypoints
        )



        # -------------------------
        # 저장 데이터
        # -------------------------

        log_data={

            "time":
            datetime.now()
            .isoformat(),

            "posture":
            posture,

            "keypoints":
            keypoints

        }



        save_log(
            log_data
        )


        print(
            log_data
        )



        time.sleep(
            CAPTURE_INTERVAL
        )



except KeyboardInterrupt:

    print(
        "\n[INFO] stopped"
    )


finally:

    picam2.stop()

    print(
        "[INFO] camera closed"
    )