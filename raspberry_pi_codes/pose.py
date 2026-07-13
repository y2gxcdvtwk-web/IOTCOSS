import cv2
import mediapipe as mp
from picamera2 import Picamera2

# ==========================
# MediaPipe Pose
# ==========================
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

mp_draw = mp.solutions.drawing_utils

# ==========================
# Picamera2
# ==========================
picam2 = Picamera2()

config = picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}
)

picam2.configure(config)
picam2.start()

print("카메라 시작")

# ==========================
# Loop
# ==========================
while True:
    frame = picam2.capture_array()

    # OpenCV 표시용(BGR 변환)
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    # MediaPipe 입력(RGB)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    results = pose.process(rgb)

    if results.pose_landmarks:
        mp_draw.draw_landmarks(
            frame,
            results.pose_landmarks,
            mp_pose.POSE_CONNECTIONS
        )

    cv2.imshow("Pose Test", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
picam2.stop()