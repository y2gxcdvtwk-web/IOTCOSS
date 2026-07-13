import cv2
import mediapipe as mp

# MediaPipe Pose 초기화
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

mp_draw = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)
print(cap.isOpened())
if not cap.isOpened():
    print("camera not opend")
    exit()
while cap.isOpened():
    success, frame = cap.read()
    print("success=",success)

    if not success:
        break

    # 좌우 반전(거울 모드)
    frame = cv2.flip(frame, 1)

    # BGR → RGB
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # Pose 추론
    results = pose.process(rgb)

    # 랜드마크가 검출되면 그리기
    if results.pose_landmarks:
        mp_draw.draw_landmarks(
            frame,
            results.pose_landmarks,
            mp_pose.POSE_CONNECTIONS
        )

    cv2.imshow("Posture Test", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()