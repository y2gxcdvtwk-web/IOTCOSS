import cv2
import json
import os
import time
import subprocess
import tempfile
import traceback
import requests
import numpy as np
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from ai_edge_litert.interpreter import Interpreter
# =========================
# 설정
# =========================
IMAGE_PATH = "temp.jpg"
LOG_PATH = "data/posture_log.jsonl"
MODEL_PATH = "yolo11n-pose.tflite"
WIDTH = 640
HEIGHT = 840
CAPTURE_INTERVAL = 0.05
SAMPLE_UPLOAD_INTERVAL = float(os.getenv("SAMPLE_UPLOAD_INTERVAL", "1.0"))
COMMAND_POLL_INTERVAL = float(os.getenv("COMMAND_POLL_INTERVAL", "2.0"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5.0"))
NECK_FORWARD_THRESHOLD = 120.0

# FastAPI analyticsServer
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://172.20.10.2:8000").rstrip("/")
DEVICE_ID = os.getenv("DEVICE_ID", "posture-camera-01")

# 확정 Mobius 구조: /postureCamera/{command,status,postureSamples,postureEvents}
AE_NAME = "postureCamera"
CONTAINERS = {
    "command": "command",
    "status": "status",
    "samples": "postureSamples",
    "events": "postureEvents",
}
POSTURE_LIGHT_AE = "postureLight"
POSTURE_LIGHT_COMMAND_CONTAINER = "command"
# =========================
# Mobius CSE
# =========================

MOBIUS_ROOT = os.getenv(
    "MOBIUS_ROOT",
    "https://platform.iotcoss.ac.kr/api/proxy/swagger/Mobius",
).rstrip("/")

MOBIUS_HEADERS = {
    "accept": "*/*",
    "X-M2M-Origin": os.getenv("MOBIUS_ORIGIN", "S"),
    "X-API-KEY": os.getenv(
        "MOBIUS_API_KEY", "REDACTED_MOBIUS_API_KEY_00000000"
    ),
    "X-AUTH-CUSTOM-LECTURE": os.getenv("MOBIUS_LECTURE", "LCT_20260002"),
    "X-AUTH-CUSTOM-CREATOR": os.getenv("MOBIUS_CREATOR", "sjuADDHD"),
    "Accept": "application/json"
}
MOBIUS_HEADERS = {key: value for key, value in MOBIUS_HEADERS.items() if value}
interpreter = None
input_details = None
output_details = None
input_shape = None


# =========================
# YOLO Load
# =========================
def load_model():
    global interpreter, input_details, output_details, input_shape
    if interpreter is not None:
        print("Model loaded")
        return interpreter, input_details, output_details, input_shape
    print("Loading model")
    try:
        interpreter = Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        input_shape = input_details[0]["shape"]
        print("[INFO] Input:", input_shape)
        print("Model loaded")
        return interpreter, input_details, output_details, input_shape
    except Exception as exc:
        print(f"Model load failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise


# =========================
# Camera
# =========================
def start_camera():
    print("Starting camera")
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
        "-"
    ]
    print(f"Camera command: {' '.join(cmd)}")
    stderr_file = tempfile.TemporaryFile(mode="w+b")
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            bufsize=10**8
        )
        process._stderr_file = stderr_file
        print(f"Camera process started: pid={process.pid}")
        time.sleep(2)
        returncode = process.poll()
        if returncode is not None:
            stderr_file.seek(0)
            stderr_text = stderr_file.read().decode(errors="replace")
            print(f"Camera process exited early: returncode={returncode}")
            print(f"Camera stderr: {stderr_text.strip()}")
            raise RuntimeError(f"rpicam-vid exited early with returncode {returncode}")
        if process.stdout is None:
            raise RuntimeError("rpicam-vid stdout is not connected")
        return process
    except Exception as exc:
        if "process" in locals() and process.poll() is None:
            process.terminate()
        stderr_file.close()
        print(f"Camera start failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise
# =========================
# Keypoints
# =========================
KEYPOINT = {
    "right_eye": 2,
    "right_ear": 4,
    "right_shoulder": 6
}
SKELETON = [
    ("right_eye", "right_ear"),
    ("right_ear", "right_shoulder")
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
            cv2.putText(
                frame,
                f"{name} ({x}, {y})",
                (x+5, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
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

    result = {
        "neck_forward": False,
        "mCRA": 0
    }

    try:

        eye = points["right_eye"]
        ear = points["right_ear"]
        shoulder = points["right_shoulder"]

        print("--------------------------------")
        print(f"Eye      : {eye}")
        print(f"Ear      : {ear}")
        print(f"Shoulder : {shoulder}")

        # Ear -> Eye 벡터
        v1 = np.array([
            eye[0] - ear[0],
            eye[1] - ear[1]
        ], dtype=np.float32)

        # Ear -> Shoulder 벡터
        v2 = np.array([
            shoulder[0] - ear[0],
            shoulder[1] - ear[1]
        ], dtype=np.float32)


        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 < 1e-6 or norm2 < 1e-6:
            return result


        v1 = v1 / norm1
        v2 = v2 / norm2


        cos_theta = np.dot(v1, v2)
        cos_theta = np.clip(cos_theta, -1.0, 1.0)

        mcra = np.degrees(np.arccos(cos_theta))


        print(f"mCRA = {mcra:.2f}")


        result["mCRA"] = round(float(mcra), 1)


        # 120도 기준 판단
        # Confirmed rule: mCRA >= 120 degrees means forward-head posture.
        result["neck_forward"] = bool(mcra >= NECK_FORWARD_THRESHOLD)


    except Exception as e:
        print("Posture error:", e)


    return result
# =========================
# Save JSON
# =========================
def _json_default(value):
    """Convert NumPy values produced by inference to JSON-compatible values."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def save_log(data):
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH,"a",encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, default=_json_default) + "\n")


def _mobius_headers(resource_type=None):
    headers = {
        **MOBIUS_HEADERS,
        "X-M2M-RI": uuid4().hex,
    }
    if resource_type:
        # IOTCOSS Swagger proxy는 vendor MIME 대신 이 형식을 요구한다.
        headers["Content-Type"] = f"application/json;ty={resource_type}"
    return headers


def create_app_session():
    """FastAPI 세션을 만들고 Mobius 이벤트에 포함할 session_id를 반환한다."""
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
    """확정된 postureCamera 컨테이너에 CIN을 생성한다."""

    url = f"{MOBIUS_ROOT}/{AE_NAME}/{CONTAINERS[container]}"

    payload = {
        "m2m:cin": {
            "con": data
        }
    }

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


def send_command(ae_name, container, data):
    """Create a command CIN in a device command container."""
    url = f"{MOBIUS_ROOT}/{ae_name}/{container}"
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
                f"[MOBIUS] command {ae_name}/{container} rejected: "
                f"HTTP {response.status_code}\n"
                f"response={response.text[:1000]}\n"
                f"payload={json.dumps(payload, ensure_ascii=False)}"
            )
            return False
        print(f"[MOBIUS] command sent: {ae_name}/{container} {data['command']}")
        return True
    except requests.RequestException as exc:
        print(f"[MOBIUS] command {ae_name}/{container} failed: {exc}")
        return False


def send_posture_light_command(session_id, posture, command=None):
    """Send a posture state command using the fixed postureLight topology."""
    if command is None:
        command = "WARNING" if posture["neck_forward"] else "NORMAL"
    return send_command(
        POSTURE_LIGHT_AE,
        POSTURE_LIGHT_COMMAND_CONTAINER,
        {
            "command": command,
            "session_id": session_id,
            "device_id": DEVICE_ID,
            "neck_forward": posture["neck_forward"],
            "mCRA": posture["mCRA"],
            "issued_at": datetime.now().isoformat(),
        },
    )


def poll_command(last_resource_name=None):
    """command/latest를 polling하고 새 명령만 반환한다."""
    url = f"{MOBIUS_ROOT}/{AE_NAME}/{CONTAINERS['command']}/latest"
    try:
        response = requests.get(
            url,
            headers=_mobius_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 404:
            return last_resource_name, None
        response.raise_for_status()
        cin = response.json().get("m2m:cin", {})
        resource_name = cin.get("rn")
        if not resource_name or resource_name == last_resource_name:
            return last_resource_name, None
        return resource_name, cin.get("con")
    except requests.RequestException as exc:
        print(f"Command polling failed: {exc}")
        return last_resource_name, None


def parse_command(command):
    if isinstance(command, str):
        try:
            return json.loads(command)
        except json.JSONDecodeError:
            return None
    if isinstance(command, dict):
        return command
    return None


def command_key(resource_name, command):
    command_id = command.get("command_id") if isinstance(command, dict) else None
    return str(command_id or resource_name or "")


def remember_startup_command():
    last_resource_name, command = poll_command(None)
    command = parse_command(command)
    if command:
        print(f"Ignoring startup command: command_id={command.get('command_id')}")
    return last_resource_name, command


def wait_for_start_command(last_resource_name, processed_commands):
    while True:
        last_resource_name, command = poll_command(last_resource_name)
        command = parse_command(command)
        if not command:
            time.sleep(COMMAND_POLL_INTERVAL)
            continue

        key = command_key(last_resource_name, command)
        if key and key in processed_commands:
            print(f"Command already processed: {command.get('command_id') or key}")
            time.sleep(COMMAND_POLL_INTERVAL)
            continue

        if str(command.get("action", "")).lower() != "start":
            if key:
                processed_commands.add(key)
            print(f"[COMMAND] Ignored non-start command: {command}")
            time.sleep(COMMAND_POLL_INTERVAL)
            continue

        print("New posture command detected")
        print(f"command_id={command.get('command_id')}")
        print(f"session_id={command.get('session_id')}")
        print(f"action={command.get('action')}")
        print("Starting posture analysis")
        if key:
            processed_commands.add(key)
        return last_resource_name, command


def run_posture_analysis(command, last_command_resource, processed_commands):
    print("Entered run_posture_analysis()")
    session_id = command.get("session_id")
    command_id = command.get("command_id")
    print(f"session_id={session_id}")
    started_at = datetime.now().isoformat()
    process = None
    frame_size = int(WIDTH * HEIGHT * 1.5)

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

    try:
        load_model()
        process = start_camera()
        print("Waiting for first camera frame")
        raw = process.stdout.read(frame_size)
        if len(raw) != frame_size:
            returncode = process.poll()
            print(
                "Camera frame read failed: "
                f"expected={frame_size}, received={len(raw)}"
            )
            if returncode is not None:
                print(f"Camera process exited early: returncode={returncode}")
                stderr_file = getattr(process, "_stderr_file", None)
                if stderr_file:
                    stderr_file.seek(0)
                    stderr_text = stderr_file.read().decode(errors="replace")
                    print(f"Camera stderr: {stderr_text.strip()}")
            raise RuntimeError("first camera frame was not received")
        print(f"First camera frame received: bytes={len(raw)}")
        print("Posture analysis running")
        send_to_mobius(
            "status",
            {
                "device_id": DEVICE_ID,
                "session_id": session_id,
                "command_id": command_id,
                "state": "running",
                "started_at": started_at,
            },
        )
    except Exception as exc:
        print(f"Posture analysis start failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        send_to_mobius(
            "status",
            {
                "device_id": DEVICE_ID,
                "session_id": session_id,
                "command_id": command_id,
                "state": "error",
                "message": str(exc),
                "occurred_at": datetime.now().isoformat(),
            },
        )
        if process:
            process.terminate()
            stderr_file = getattr(process, "_stderr_file", None)
            if stderr_file:
                stderr_file.close()
        return last_command_resource

    last_sample_upload = 0.0
    last_command_poll = 0.0
    previous_neck_forward = None

    try:
        while True:
            if len(raw)!=frame_size:
                print(
                    "Camera frame read failed: "
                    f"expected={frame_size}, received={len(raw)}"
                )
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
                    "neck_forward": False,
                    "mCRA": 0
                }

            cv2.putText(
                frame,
                f"mCRA:{posture['mCRA']:.1f}",
                (20,50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255,255,0),
                2
    )
            cv2.putText(
            frame,
            f"Neck Forward:{posture['neck_forward']}",
            (20,90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0,255,0),
            2
        )
            save_log({"time":datetime.now().isoformat(),
                      "session_id":session_id,
                      "posture":posture,
                      "keypoints":keypoints
                      })
            now = time.monotonic()
            measured_at = datetime.now().isoformat()

            # ?꾨젅?꾨쭏??蹂대궡吏 ?딄퀬 ?ㅼ젙??二쇨린濡??섑뵆???꾩넚?쒕떎.
            if now - last_sample_upload >= SAMPLE_UPLOAD_INTERVAL:
                sample_sent = send_to_mobius(
                    "samples",
                    {
                        "device_id": DEVICE_ID,
                        "session_id": session_id,
                        "measured_at": measured_at,
                        "neck_forward": posture["neck_forward"],
                        "mCRA": posture["mCRA"],
                    },
                )
                if sample_sent:
                    print(
                        "Posture sample sent: "
                        f"session_id={session_id}, "
                        f"mCRA={posture['mCRA']}, "
                        f"neck_forward={posture['neck_forward']}"
                    )
                else:
                    print(
                        "Posture sample send failed: "
                        f"session_id={session_id}, "
                        f"mCRA={posture['mCRA']}, "
                        f"neck_forward={posture['neck_forward']}"
                    )
                last_sample_upload = now

            # ?먯꽭 ?곹깭媛 諛붾??쒓컙留?event 而⑦뀒?대꼫??湲곕줉?쒕떎.
            posture_changed = (
                previous_neck_forward is None
                or posture["neck_forward"] != previous_neck_forward
            )
            if posture_changed:
                send_posture_light_command(session_id, posture)
                if previous_neck_forward is not None:
                    event_name = (
                        "neck_forward_detected"
                        if posture["neck_forward"]
                        else "posture_recovered"
                    )
                    event_sent = send_to_mobius(
                        "events",
                        {
                            "device_id": DEVICE_ID,
                            "session_id": session_id,
                            "occurred_at": measured_at,
                            "event": event_name,
                            "neck_forward": posture["neck_forward"],
                            "mCRA": posture["mCRA"],
                        },
                    )
                    if event_sent:
                        print(f"Posture event sent: session_id={session_id}, event={event_name}")
            previous_neck_forward = posture["neck_forward"]

            if now - last_command_poll >= COMMAND_POLL_INTERVAL:
                last_command_resource, next_command = poll_command(last_command_resource)
                next_command = parse_command(next_command)
                if next_command:
                    next_key = command_key(last_command_resource, next_command)
                    if next_key and next_key in processed_commands:
                        print(f"Command already processed: {next_command.get('command_id') or next_key}")
                    elif str(next_command.get("action", "")).lower() == "stop":
                        if next_key:
                            processed_commands.add(next_key)
                        print("[COMMAND] Stop requested")
                        break
                    elif str(next_command.get("action", "")).lower() == "start":
                        if next_key:
                            processed_commands.add(next_key)
                        print(
                            "[COMMAND] Start ignored while posture analysis is already running: "
                            f"{next_command.get('command_id') or next_key}"
                        )
                    else:
                        if next_key:
                            processed_commands.add(next_key)
                        print(f"[COMMAND] Ignored command: {next_command}")
                last_command_poll = now
            cv2.imshow("YOLO11 Pose",frame)
            if cv2.waitKey(1)&0xff == ord('q'):
                break
            time.sleep(CAPTURE_INTERVAL)
            raw = process.stdout.read(frame_size)
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
        send_posture_light_command(
            session_id,
            {"neck_forward": False, "mCRA": 0},
            command="OFF",
        )
        if process:
            process.terminate()
            stderr_file = getattr(process, "_stderr_file", None)
            if stderr_file:
                stderr_file.close()
        cv2.destroyAllWindows()
        print("Camera closed")
    return last_command_resource


def run_command_service():
    print("Posture camera service started")
    send_to_mobius(
        "status",
        {
            "device_id": DEVICE_ID,
            "session_id": None,
            "state": "online",
            "started_at": datetime.now().isoformat(),
        },
    )
    last_command_resource, startup_command = remember_startup_command()
    processed_commands = set()
    startup_key = command_key(last_command_resource, startup_command)
    if startup_key:
        processed_commands.add(startup_key)

    print("Waiting for postureCamera/command")
    while True:
        last_command_resource, command = wait_for_start_command(
            last_command_resource,
            processed_commands,
        )
        print("Calling run_posture_analysis()")
        last_command_resource = run_posture_analysis(
            command,
            last_command_resource,
            processed_commands,
        )
        print("Waiting for postureCamera/command")
# =========================
# Main
# =========================
if __name__ == "__main__":
    try:
        run_command_service()
    except KeyboardInterrupt:
        print("Stopped")
