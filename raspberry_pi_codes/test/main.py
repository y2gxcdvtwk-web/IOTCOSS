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

sx = WIDTH / 640
sy = HEIGHT / 640

# =========================
# YOLO TFLite Load
# =========================

print("[INFO] Loading model...")

interpreter = Interpreter(
    model_path=MODEL_PATH
)

interpreter.allocate_tensors()


input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

input_shape = input_details[0]["shape"]

print("[INFO] Input shape:", input_shape)


# =========================
# Camera
# =========================

print("[INFO] Starting camera...")


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
# Skeleton
# =========================

SKELETON = [

    ("nose","left_shoulder"),
    ("nose","right_shoulder"),

    ("left_shoulder","right_shoulder"),

    ("left_shoulder","left_elbow"),
    ("left_elbow","left_wrist"),

    ("right_shoulder","right_elbow"),
    ("right_elbow","right_wrist"),

    ("left_shoulder","left_hip"),
    ("right_shoulder","right_hip"),

    ("left_hip","right_hip")

]



def draw_skeleton(frame, points):


    # 관절 점

    for name, point in points.items():

        x = int(point[0] * sx)
        y = int(point[1] * sy)

        conf = point[2]


        if conf > 0.3:

            cv2.circle(
                frame,
                (x,y),
                5,
                (0,255,0),
                -1
            )


            cv2.putText(
                frame,
                name,
                (x+5,y-5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (255,255,255),
                1
            )



    # 연결선

    for a,b in SKELETON:


        if a in points and b in points:


            x1,y1,c1 = points[a]

            x2,y2,c2 = points[b]

            x1 *= sx
            y1 *= sy

            x2 *= sx
            y2 *= sy

            if c1 > 0.3 and c2 > 0.3:


                cv2.line(

                    frame,

                    (int(x1),int(y1)),

                    (int(x2),int(y2)),

                    (255,0,0),

                    2

                )


    return frame





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
# Output -> Keypoint
# =========================


def extract_keypoints(output):


    points = {}


    output = np.squeeze(output)


    # (56,8400) -> (8400,56)

    output = output.T



    confidence = output[:,4]


    index = np.argmax(
        confidence
    )


    person = output[index]


    keypoints = person[5:]


    keypoints = keypoints.reshape(
        17,
        3
    )



    for name,idx in KEYPOINT.items():


        points[name] = [

            float(keypoints[idx][0]),

            float(keypoints[idx][1]),

            float(keypoints[idx][2])

        ]


    return points





# =========================
# 자세 분석
# =========================


def calculate_posture(points):
    for k, v in points.items():

        if v[2] < 0.3:
            return {
                "neck_forward": False,
                "back_bent": False,
                "score": 100
            }
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



        shoulder_x = (

            ls[0]+rs[0]

        )/2



        hip_x = (

            lh[0]+rh[0]

        )/2



        # 거북목

        neck_distance = abs(

            nose[0]-shoulder_x

        )



        if neck_distance > 35:

            result["neck_forward"] = True

            score -= 25



        # 허리 굽음

        body_angle = abs(

            shoulder_x-hip_x

        )



        if body_angle > 40:

            result["back_bent"] = True

            score -= 25



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
# Main Loop
# =========================


print("[INFO] Start monitoring")


try:


    while True:


        raw_frame = process.stdout.read(
            frame_size
        )


        if len(raw_frame)!=frame_size:

            break



        yuv_frame = np.frombuffer(

            raw_frame,

            dtype=np.uint8

        ).reshape(

            int(HEIGHT*1.5),

            WIDTH

        )



        frame = cv2.cvtColor(

            yuv_frame,

            cv2.COLOR_YUV2BGR_I420

        )



        # temp.jpg 저장

        cv2.imwrite(

            IMAGE_PATH,

            frame

        )




        # =====================
        # YOLO inference
        # =====================


        input_data = preprocess(
            frame
        )


        interpreter.set_tensor(

            input_details[0]["index"],

            input_data

        )


        interpreter.invoke()



        output = interpreter.get_tensor(

            output_details[0]["index"]

        )
        print(output.shape)



        keypoints = extract_keypoints(

            output

        )
        print(keypoints)



        posture = calculate_posture(

            keypoints

        )



        # 스켈레톤 출력

        frame = draw_skeleton(

            frame,

            keypoints

        )



        # 점수 출력

        cv2.putText(

            frame,

            f"Score : {posture['score']}",

            (20,40),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0,255,0),

            2

        )



        log_data = {


            "time":

            datetime.now().isoformat(),


            "posture":

            posture,


            "keypoints":

            keypoints

        }



        save_log(

            log_data

        )


        print(log_data)



        cv2.imshow(

            "YOLO11 Pose",

            frame

        )



        if cv2.waitKey(1)&0xff == ord('q'):

            break



        time.sleep(

            CAPTURE_INTERVAL

        )




except KeyboardInterrupt:


    print("\nStopped")



finally:


    process.terminate()

    cv2.destroyAllWindows()

    print("Camera closed")