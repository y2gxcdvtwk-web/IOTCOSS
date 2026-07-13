import cv2
import json
import time
import subprocess
import numpy as np

from datetime import datetime
from ai_edge_litert.interpreter import Interpreter


# =========================
# 설정
# =========================

IMAGE_PATH = "temp.jpg"
LOG_PATH = "data/posture_log.jsonl"

MODEL_PATH = "yolo11n-pose.tflite"

WIDTH = 640
HEIGHT = 480

CAPTURE_INTERVAL = 1.5


# =========================
# YOLO TFLite Load
# =========================

print("[INFO] Loading TFLite model")

interpreter = Interpreter(
    model_path=MODEL_PATH
)

interpreter.allocate_tensors()


input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()


input_shape = input_details[0]["shape"]

print(
    "[INFO] input shape:",
    input_shape
)


# =========================
# Camera
# =========================


print("[INFO] Starting camera")


cmd = [
    "rpicam-vid",
    "-t",
    "0",
    "--codec",
    "yuv420",
    "--width",
    str(WIDTH),
    "--height",
    str(HEIGHT),
    "--framerate",
    "15",
    "-o",
    "-"
]


process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    bufsize=10**8
)


time.sleep(2)


frame_size = int(
    WIDTH * HEIGHT * 1.5
)


print("[INFO] Camera ready")



# =========================
# Keypoint
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
# Preprocess
# =========================


def preprocess(frame):

    img = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2RGB
    )


    img = cv2.resize(
        img,
        (640,640)
    )


    img = img.astype(
        np.float32
    ) / 255.0


    # NCHW 모델
    if input_shape[1] == 3:

        img = np.transpose(
            img,
            (2,0,1)
        )


    img = np.expand_dims(
        img,
        axis=0
    )


    return img





# =========================
# YOLO Output 처리
# =========================


def extract_keypoints(output):

    """
    YOLO11 pose output

    [1,56,8400]

    """

    points={}


    output = np.squeeze(
        output
    )


    # transpose
    output = output.T


    # confidence 최대 사람 선택

    confs = output[:,4]

    index = np.argmax(
        confs
    )


    person = output[index]


    keypoints = person[5:]


    keypoints = keypoints.reshape(
        17,3
    )



    for name,idx in KEYPOINT.items():

        points[name]=[
            float(keypoints[idx][0]),
            float(keypoints[idx][1]),
            float(keypoints[idx][2])
        ]


    return points





# =========================
# 자세 분석
# =========================


def calculate_posture(points):


    score=100


    result={

        "neck_forward":False,

        "back_bent":False,

        "score":100
    }



    try:

        nose=points["nose"]

        ls=points["left_shoulder"]

        rs=points["right_shoulder"]

        lh=points["left_hip"]

        rh=points["right_hip"]



        shoulder_x=(

            ls[0]+rs[0]

        )/2



        hip_x=(

            lh[0]+rh[0]

        )/2




        # 거북목

        neck_distance = abs(

            nose[0]-shoulder_x

        )


        if neck_distance > 35:

            result["neck_forward"]=True

            score-=25





        # 허리 굽음


        body_angle = abs(

            shoulder_x-hip_x

        )


        if body_angle >40:

            result["back_bent"]=True

            score-=25



        score=max(
            score,
            0
        )


        result["score"]=score



    except Exception as e:

        print(
            "[WARN]",
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
# Main
# =========================


print(
    "[INFO] Start monitoring"
)


try:


    while True:


        raw = process.stdout.read(
            frame_size
        )


        if len(raw)!=frame_size:
            break



        yuv = np.frombuffer(
            raw,
            dtype=np.uint8
        )


        yuv = yuv.reshape(
            int(HEIGHT*1.5),
            WIDTH
        )


        frame=cv2.cvtColor(
            yuv,
            cv2.COLOR_YUV2BGR_I420
        )



        # temp.jpg 저장

        cv2.imwrite(
            IMAGE_PATH,
            frame
        )




        # =================
        # inference
        # =================


        input_data=preprocess(
            frame
        )


        interpreter.set_tensor(

            input_details[0]["index"],

            input_data

        )


        interpreter.invoke()



        output=interpreter.get_tensor(

            output_details[0]["index"]

        )



        keypoints=extract_keypoints(
            output
        )



        posture=calculate_posture(
            keypoints
        )




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



        cv2.putText(

            frame,

            f"Score:{posture['score']}",

            (20,40),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0,255,0),

            2

        )


        cv2.imshow(
            "YOLO11 Pose",
            frame
        )



        if cv2.waitKey(1)&0xff==ord('q'):
            break



        time.sleep(
            CAPTURE_INTERVAL
        )



except KeyboardInterrupt:

    print(
        "Stopped"
    )


finally:

    process.terminate()

    cv2.destroyAllWindows()

    print(
        "Camera closed"
    )