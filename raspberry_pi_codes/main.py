import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import requests
from ai_edge_litert.interpreter import Interpreter


IMAGE_PATH = "temp.jpg"
LOG_PATH = "data/posture_log.jsonl"
MODEL_PATH = os.getenv("MODEL_PATH", "yolo11n-pose.tflite")
WIDTH = int(os.getenv("CAMERA_WIDTH", "640"))
HEIGHT = int(os.getenv("CAMERA_HEIGHT", "840"))
CAPTURE_INTERVAL = float(os.getenv("CAPTURE_INTERVAL", "0.05"))
SAMPLE_UPLOAD_INTERVAL = float(os.getenv("SAMPLE_UPLOAD_INTERVAL", "1.0"))
COMMAND_POLL_INTERVAL = float(os.getenv("COMMAND_POLL_INTERVAL", "1.0"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5.0"))
NECK_FORWARD_THRESHOLD = float(os.getenv("NECK_FORWARD_THRESHOLD", "120.0"))

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://172.20.10.2:8000").rstrip("/")
DEVICE_ID = os.getenv("DEVICE_ID", "posture-camera-01")

AE_NAME = "postureCamera"
CONTAINERS = {
    "command": "command",
    "status": "status",
    "samples": "postureSamples",
    "events": "postureEvents",
}

MOBIUS_ROOT = os.getenv(
    "MOBIUS_ROOT",
    "https://platform.iotcoss.ac.kr/api/proxy/swagger/Mobius",
).rstrip("/")

MOBIUS_HEADERS = {
    "accept": "*/*",
    "X-M2M-Origin": os.getenv("MOBIUS_ORIGIN", "S"),
    "X-API-KEY": os.getenv("MOBIUS_API_KEY", ""),
    "X-AUTH-CUSTOM-LECTURE": os.getenv("MOBIUS_LECTURE", "LCT_20260002"),
    "X-AUTH-CUSTOM-CREATOR": os.getenv("MOBIUS_CREATOR", "sjuADDHD"),
    "Accept": "application/json",
}
MOBIUS_HEADERS = {key: value for key, value in MOBIUS_HEADERS.items() if value}

KEYPOINT = {
    "right_eye": 2,
    "right_ear": 4,
    "right_shoulder": 6,
}
SKELETON = [
    ("right_eye", "right_ear"),
    ("right_ear", "right_shoulder"),
]


def _mobius_headers(resource_type=None):
    headers = {
        **MOBIUS_HEADERS,
        "X-M2M-RI": uuid4().hex,
    }
    if resource_type:
        headers["Content-Type"] = f"application/json;ty={resource_type}"
    return headers


def create_app_session(command):
    command_session_id = command.get("session_id") if isinstance(command, dict) else None
    if command_session_id:
        print(f"[APP] Using command session: {command_session_id}")
        return command_session_id
    try:
        response = requests.post(
            f"{APP_BASE_URL}/api/v1/sessions",
            json={
                "metadata": {
                    "device_id": DEVICE_ID,
                    "device": "Raspberry Pi",
                    "ae": AE_NAME,
                    "model": MODEL_PATH,
                },
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        session_id = response.json()["id"]
        print(f"[APP] Session started: {session_id}")
        return session_id
    except requests.RequestException as exc:
        print(f"[APP] Session start failed; offline mode: {exc}")
        return None


def close_app_session(session_id):
    if not session_id:
        return
    try:
        response = requests.delete(
            f"{APP_BASE_URL}/api/v1/sessions/{session_id}",
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        print(f"[APP] Session closed: {session_id}")
    except requests.RequestException as exc:
        print(f"[APP] Session close failed: {exc}")


def send_to_mobius(container, data):
    url = f"{MOBIUS_ROOT}/{AE_NAME}/{CONTAINERS[container]}"
    payload = {"m2m:cin": {"con": data}}
    try:
        response = requests.post(
            url,
            headers=_mobius_headers(4),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            print(
                f"[MOBIUS] {container} rejected: HTTP {response.status_code}\n"
                f"response={response.text[:1000]}\n"
                f"payload={json.dumps(payload, ensure_ascii=False)}"
            )
            return False
        return True
    except requests.RequestException as exc:
        print(f"[MOBIUS] {container} send failed: {exc}")
        return False


def poll_command(last_resource_name=None):
    url = f"{MOBIUS_ROOT}/{AE_NAME}/{CONTAINERS['command']}/latest"
    try:
        response = requests.get(url, headers=_mobius_headers(), timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            return last_resource_name, None
        response.raise_for_status()
        cin = response.json().get("m2m:cin", {})
        resource_name = cin.get("rn")
        if not resource_name or resource_name == last_resource_name:
            return last_resource_name, None
        return resource_name, cin.get("con")
    except requests.RequestException as exc:
        print(f"[MOBIUS] command polling failed: {exc}")
        return last_resource_name, None


def remember_latest_command_on_startup():
    resource_name, command = poll_command(None)
    if resource_name:
        print(f"[COMMAND] Ignoring stale command on boot: {resource_name} {command}")
    return resource_name


def wait_for_start_command(last_resource_name):
    send_to_mobius(
        "status",
        {
            "device_id": DEVICE_ID,
            "state": "waiting_for_start",
            "started_at": datetime.now().isoformat(),
        },
    )
    print("[INFO] Waiting for button A START command")
    while True:
        last_resource_name, command = poll_command(last_resource_name)
        if isinstance(command, dict):
            print(f"[COMMAND] {command}")
            if str(command.get("action", "")).lower() == "start":
                return last_resource_name, command
        time.sleep(COMMAND_POLL_INTERVAL)


def load_model():
    print("[INFO] Loading model")
    interpreter = Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    input_shape = input_details[0]["shape"]
    print("[INFO] Input:", input_shape)
    return interpreter, input_details, output_details, input_shape


def start_camera():
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
        "30",
        "-o",
        "-",
    ]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=10**8,
    )
    time.sleep(2)
    print("[INFO] Camera ready")
    return process


def draw_skeleton(frame, points):
    for name, point in points.items():
        x = int(point[0] * WIDTH)
        y = int(point[1] * HEIGHT)
        conf = point[2]
        if conf > 0.3:
            cv2.circle(frame, (x, y), 6, (0, 255, 0), -1)
            cv2.putText(
                frame,
                f"{name} ({x}, {y})",
                (x + 5, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
            )
    for a, b in SKELETON:
        if a in points and b in points:
            x1, y1, c1 = points[a]
            x2, y2, c2 = points[b]
            if c1 > 0.3 and c2 > 0.3:
                cv2.line(
                    frame,
                    (int(x1 * WIDTH), int(y1 * HEIGHT)),
                    (int(x2 * WIDTH), int(y2 * HEIGHT)),
                    (255, 0, 0),
                    3,
                )
    return frame


def preprocess(frame, input_shape):
    img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (640, 640))
    img = img.astype(np.float32) / 255.0
    if input_shape[1] == 3:
        img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, 0)
    return img


def extract_keypoints(output):
    points = {}
    output = output[0]
    if output.shape[0] == 56:
        output = output.T
    elif output.shape[1] != 56:
        print("Unknown output")
        return points
    person_score = output[:, 4]
    index = np.argmax(person_score)
    person = output[index]
    kpts = person[5:].reshape(17, 3)
    for name, idx in KEYPOINT.items():
        points[name] = [
            float(kpts[idx][0]),
            float(kpts[idx][1]),
            float(kpts[idx][2]),
        ]
    return points


def calculate_posture(points):
    result = {"neck_forward": False, "mCRA": 0}
    try:
        eye = points["right_eye"]
        ear = points["right_ear"]
        shoulder = points["right_shoulder"]

        v1 = np.array([eye[0] - ear[0], eye[1] - ear[1]], dtype=np.float32)
        v2 = np.array([shoulder[0] - ear[0], shoulder[1] - ear[1]], dtype=np.float32)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 < 1e-6 or norm2 < 1e-6:
            return result

        cos_theta = np.dot(v1 / norm1, v2 / norm2)
        mcra = np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0)))
        result["mCRA"] = round(float(mcra), 1)
        result["neck_forward"] = bool(mcra >= NECK_FORWARD_THRESHOLD)
    except Exception as exc:
        print("Posture error:", exc)
    return result


def save_log(data):
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(data, ensure_ascii=False) + "\n")


def run_analysis(command, last_command_resource):
    session_id = create_app_session(command)
    command_id = command.get("command_id") if isinstance(command, dict) else None
    started_at = datetime.now().isoformat()
    send_to_mobius(
        "status",
        {
            "device_id": DEVICE_ID,
            "session_id": session_id,
            "command_id": command_id,
            "state": "analyzing",
            "started_at": started_at,
        },
    )

    interpreter, input_details, output_details, input_shape = load_model()
    process = start_camera()
    frame_size = int(WIDTH * HEIGHT * 1.5)
    last_sample_upload = 0.0
    last_command_poll = 0.0
    previous_neck_forward = None

    try:
        while True:
            raw = process.stdout.read(frame_size)
            if len(raw) != frame_size:
                break

            yuv = np.frombuffer(raw, dtype=np.uint8).reshape(int(HEIGHT * 1.5), WIDTH)
            frame = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
            cv2.imwrite(IMAGE_PATH, frame)

            input_data = preprocess(frame, input_shape)
            interpreter.set_tensor(input_details[0]["index"], input_data)
            interpreter.invoke()
            output = interpreter.get_tensor(output_details[0]["index"])
            keypoints = extract_keypoints(output)
            if keypoints:
                posture = calculate_posture(keypoints)
                frame = draw_skeleton(frame, keypoints)
            else:
                posture = {"neck_forward": False, "mCRA": 0}

            cv2.putText(
                frame,
                f"mCRA:{posture['mCRA']:.1f}",
                (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 0),
                2,
            )
            cv2.putText(
                frame,
                f"Neck Forward:{posture['neck_forward']}",
                (20, 90),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )

            measured_at = datetime.now().isoformat()
            save_log(
                {
                    "time": measured_at,
                    "session_id": session_id,
                    "posture": posture,
                    "keypoints": keypoints,
                }
            )

            now = time.monotonic()
            if now - last_sample_upload >= SAMPLE_UPLOAD_INTERVAL:
                send_to_mobius(
                    "samples",
                    {
                        "device_id": DEVICE_ID,
                        "session_id": session_id,
                        "measured_at": measured_at,
                        "neck_forward": posture["neck_forward"],
                        "mCRA": posture["mCRA"],
                    },
                )
                last_sample_upload = now

            if (
                previous_neck_forward is not None
                and posture["neck_forward"] != previous_neck_forward
            ):
                send_to_mobius(
                    "events",
                    {
                        "device_id": DEVICE_ID,
                        "session_id": session_id,
                        "occurred_at": measured_at,
                        "event": (
                            "neck_forward_detected"
                            if posture["neck_forward"]
                            else "posture_recovered"
                        ),
                        "neck_forward": posture["neck_forward"],
                        "mCRA": posture["mCRA"],
                    },
                )
            previous_neck_forward = posture["neck_forward"]

            if now - last_command_poll >= COMMAND_POLL_INTERVAL:
                last_command_resource, next_command = poll_command(last_command_resource)
                if isinstance(next_command, dict):
                    print(f"[COMMAND] {next_command}")
                    action = str(next_command.get("action", "")).lower()
                    if action == "stop":
                        print("[COMMAND] Stop requested")
                        break
                last_command_poll = now

            cv2.imshow("YOLO11 Pose", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            time.sleep(CAPTURE_INTERVAL)
    finally:
        send_to_mobius(
            "status",
            {
                "device_id": DEVICE_ID,
                "session_id": session_id,
                "command_id": command_id,
                "state": "offline",
                "stopped_at": datetime.now().isoformat(),
            },
        )
        process.terminate()
        cv2.destroyAllWindows()
        print("Camera closed")
    return last_command_resource


def main():
    print("[INFO] Start")
    last_command_resource = remember_latest_command_on_startup()
    try:
        while True:
            last_command_resource, command = wait_for_start_command(last_command_resource)
            last_command_resource = run_analysis(command, last_command_resource)
    except KeyboardInterrupt:
        print("Stopped")


if __name__ == "__main__":
    main()
