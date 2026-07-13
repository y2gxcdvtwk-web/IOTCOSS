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
HEIGHT = 840

CAPTURE_INTERVAL = 1.5



# =========================
# YOLO Load
# =========================

print("[INFO] Loading model")

interpreter = Interpreter(
    model_path=MODEL_PATH
)

interpreter.allocate_tensors()


input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()


input_shape = input_details[0]["shape"]

print(
    "[INFO] Input:",
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
# Keypoints
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




# =========================
# Draw Skeleton
# =========================


def draw_skeleton(frame, points):


    for name, point in points.items():


        x = int(point[0] * WIDTH)

        y = int(point[1] * HEIGHT)

        conf = point[2]


        if conf > 0.3:


            cv2.circle(

                frame,

                (x,y),

                6,

                (0,255,0),

                -1

            )



            cv2.putText(

                frame,

                name,

                (x+5,y),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.4,

                (255,255,255),

                1

            )




    for a,b in SKELETON:


        if a in points and b in points:


            x1,y1,c1 = points[a]

            x2,y2,c2 = points[b]


            if c1 > 0.3 and c2 > 0.3:


                cv2.line(

                    frame,

                    (

                        int(x1*WIDTH),

                        int(y1*HEIGHT)

                    ),

                    (

                        int(x2*WIDTH),

                        int(y2*HEIGHT)

                    ),

                    (255,0,0),

                    3

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

        0

    )


    return img





# =========================
# Extract Pose
# =========================


def extract_keypoints(output):


    points={}


    print(
        "OUTPUT SHAPE:",
        output.shape
    )


    output = output[0]



    if output.shape[0] == 56:

        output = output.T



    elif output.shape[1] == 56:

        pass


    else:

        print("Unknown output")
        return points




    person_score = output[:,4]


    index = np.argmax(

        person_score

    )


    person = output[index]


    kpts = person[5:]


    kpts = kpts.reshape(

        17,

        3

    )



    for name,idx in KEYPOINT.items():


        points[name]=[

            float(kpts[idx][0]),

            float(kpts[idx][1]),

            float(kpts[idx][2])

        ]



    return points





# =========================
# Posture
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



        # 정규화 -> pixel

        neck_distance = abs(

            nose[0]-shoulder_x

        ) * WIDTH



        if neck_distance > 35:


            result["neck_forward"]=True

            score -= 25





        body_angle = abs(

            shoulder_x-hip_x

        ) * WIDTH



        if body_angle > 40:


            result["back_bent"]=True

            score -= 25




        score=max(

            score,

            0

        )


        result["score"]=score



    except Exception as e:

        print(
            "Posture error:",
            e
        )


    return result





# =========================
# Save JSON
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


print("[INFO] Start")


try:


    while True:


        raw = process.stdout.read(

            frame_size

        )


        if len(raw)!=frame_size:

            break



        yuv=np.frombuffer(

            raw,

            dtype=np.uint8

        ).reshape(

            int(HEIGHT*1.5),

            WIDTH

        )



        frame=cv2.cvtColor(

            yuv,

            cv2.COLOR_YUV2BGR_I420

        )



        cv2.imwrite(

            IMAGE_PATH,

            frame

        )




        # inference

        input_data=preprocess(frame)


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


        print(keypoints)



        if len(keypoints)>0:


            posture=calculate_posture(

                keypoints

            )


            frame=draw_skeleton(

                frame,

                keypoints

            )


        else:


            posture={

                "score":0

            }




        cv2.putText(

            frame,

            f"Score : {posture['score']}",

            (20,50),

            cv2.FONT_HERSHEY_SIMPLEX,

            1.2,

            (0,255,0),

            3

        )



        save_log({

            "time":
            datetime.now().isoformat(),

            "posture":
            posture,

            "keypoints":
            keypoints

        })



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

    print("Stopped")



finally:

    process.terminate()

    cv2.destroyAllWindows()

    print("Camera closed")