import cv2
import mediapipe as mp
import time

# -------------------------------
# MediaPipe 초기화
# -------------------------------
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=True)

# -------------------------------
# 카메라 연결
# -------------------------------
cap = cv2.VideoCapture(0)

# 거북목 기준값(실험을 통해 조정)
THRESHOLD = 0.08

print("시스템 시작")

while True:

    print("사진 촬영 중...")

    ret, frame = cap.read()

    if not ret:
        print("카메라 오류")
        break

    # RGB 변환
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 자세 분석
    result = pose.process(rgb)

    if result.pose_landmarks:

        landmark = result.pose_landmarks.landmark

        # 왼쪽 귀, 왼쪽 어깨
        ear = landmark[7]
        shoulder = landmark[11]

        # 귀가 어깨보다 얼마나 앞으로 나왔는지
        distance = ear.x - shoulder.x

        print("--------------------------------")
        print("귀 x :", ear.x)
        print("어깨 x :", shoulder.x)
        print("거리 :", distance)

        if distance > THRESHOLD:
            print("거북목")
            # 책상 제어 함수
            # control_desk()

        else:
            print("정상")

    else:
        print("사람을 인식하지 못했습니다.")

    print("5분 대기...\n")

    # 5분 대기
    time.sleep(300)

cap.release()
