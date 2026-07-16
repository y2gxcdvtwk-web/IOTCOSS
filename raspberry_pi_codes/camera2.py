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
interpreter = Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
input_shape = input_details[0]["shape"]
print("[INFO] Input:",input_shape)
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
frame_size = int(WIDTH * HEIGHT * 1.5)
print("[INFO] Camera ready")
# =========================
# Keypoints
# =========================
KEYPOINT = {
    "nose":0,

    "left_ear":3,
    "right_ear":4,

    "left_shoulder":5,
    "right_shoulder":6,

    "left_hip":11,
    "right_hip":12
}
SKELETON = [
    ("left_ear","right_ear"),

    ("left_ear", "nose"),
    ("right_ear", "nose"),

    ("left_ear","left_shoulder"),
    ("right_ear","right_shoulder"),

    ("left_shoulder","right_shoulder"),

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
            cv2.circle(frame, (x,y), 6, (0,255,0), -1)
            cv2.putText(frame, name,
                        (x+5,y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
    for a,b in SKELETON:
        if a in points and b in points:
            x1,y1,c1 = points[a]
            x2,y2,c2 = points[b]
            if c1 > 0.3 and c2 > 0.3:
                cv2.line(
                    frame,
                    (int(x1*WIDTH), int(y1*HEIGHT)),
                    (int(x2*WIDTH), int(y2*HEIGHT)),
                    (255,0,0), 3)
    return frame
# =========================
# Preprocess
# =========================
def preprocess(frame):
    img = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
    img = cv2.resize(img,(640,640))
    img = img.astype(np.float32) / 255.0
    if input_shape[1] == 3:
        img = np.transpose(img,(2,0,1))
    img = np.expand_dims(img,0)
    return img
# =========================
# Extract Pose
# =========================
def extract_keypoints(output):
    points={}
    print("OUTPUT SHAPE:",output.shape)
    output = output[0]
    if output.shape[0] == 56:
        output = output.T
    elif output.shape[1] == 56:
        pass
    else:
        print("Unknown output")
        return points
    person_score = output[:,4]
    index = np.argmax(person_score)
    person = output[index]
    kpts = person[5:]
    kpts = kpts.reshape(17,3)
    for name,idx in KEYPOINT.items():
        points[name]=[
            float(kpts[idx][0]),
            float(kpts[idx][1]),
            float(kpts[idx][2])
        ]
    return points
def calculate_posture(points):

    score = 100

    result = {
        "neck_forward": False,
        "back_bent": False,
        "score": 100,
        "SA": 0
    }

    try:

        # 귀와 어깨 선택
        if points["right_ear"][2] > points["left_ear"][2]:
            ear = points["right_ear"]
            shoulder = points["right_shoulder"]
        else:
            ear = points["left_ear"]
            shoulder = points["left_shoulder"]

        # 골반 중심
        hip = [
            (points["left_hip"][0] + points["right_hip"][0]) / 2,
            (points["left_hip"][1] + points["right_hip"][1]) / 2
        ]

        # 벡터 생성
        v1 = np.array([
            ear[0] - shoulder[0],
            ear[1] - shoulder[1]
        ])

        v2 = np.array([
            hip[0] - shoulder[0],
            hip[1] - shoulder[1]
        ])

        # 각도 계산
        cos_theta = np.dot(v1, v2) / (
            np.linalg.norm(v1) * np.linalg.norm(v2)
        )

        cos_theta = np.clip(cos_theta, -1.0, 1.0)

        angle = np.degrees(np.arccos(cos_theta))

        # Shoulder Angle
        sa = angle - 90

        result["SA"] = round(sa, 1)

        # 점수 계산
        if sa > 10:
            score -= 10

        if sa > 15:
            score -= 15

        if sa > 20:
            score -= 20

        if sa > 25:
            score -= 30

        score = max(score, 0)

        result["score"] = score

        if sa > 15:
            result["neck_forward"] = True

    except Exception as e:
        print("Posture error:", e)

    return result
# =========================
# Save JSON
# =========================
def save_log(data):
    with open(LOG_PATH,"a",encoding="utf-8") as f:
        f.write(json.dumps(data,ensure_ascii=False)+"\n")
# =========================
# Main
# =========================
print("[INFO] Start")
try:
    while True:
        raw = process.stdout.read(frame_size)
        if len(raw)!=frame_size:
            break
        yuv=np.frombuffer(raw,dtype=np.uint8).reshape(int(HEIGHT*1.5),WIDTH)
        frame=cv2.cvtColor(yuv,cv2.COLOR_YUV2BGR_I420)
        cv2.imwrite(IMAGE_PATH,frame)
        # inference
        input_data=preprocess(frame)
        interpreter.set_tensor(input_details[0]["index"],input_data)
        interpreter.invoke()
        output=interpreter.get_tensor(output_details[0]["index"])
        keypoints=extract_keypoints(output)
        print(keypoints)
        if len(keypoints)>0:
            posture=calculate_posture(keypoints)
            frame=draw_skeleton(frame,keypoints)
        else:
            posture = {
                "score": 0,
                "SA": 0
    }
        cv2.putText(frame, f"Score:{posture['score']}",
                    (20,50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,255,0), 3)
        cv2.putText(
    frame,
    f"SA:{posture['SA']:.1f}",
    (20,100),
    cv2.FONT_HERSHEY_SIMPLEX,
    1,
    (255,255,0),
    2
)
        save_log({"time":datetime.now().isoformat(),
                  "posture":posture,
                  "keypoints":keypoints
                  })
        cv2.imshow("YOLO11 Pose",frame)
        if cv2.waitKey(1)&0xff == ord('q'):
            break
        time.sleep(CAPTURE_INTERVAL)
except KeyboardInterrupt:
    print("Stopped")
finally:
    process.terminate()
    cv2.destroyAllWindows()
    print("Camera closed")