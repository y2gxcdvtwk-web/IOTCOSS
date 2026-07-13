import cv2
import mediapipe as mp
import math
import time
from datetime import datetime

# ==========================
# MediaPipe 초기화
# ==========================

mp_pose = mp.solutions.pose

pose = mp_pose.Pose(
    static_image_mode=True,
    model_complexity=1,
    min_detection_confidence=0.5
)

# ==========================
# 카메라 연결
# ==========================

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("카메라를 열 수 없습니다.")
    exit()

# ==========================
# 함수
# ==========================

def capture_image():

    ret, frame = cap.read()

    if not ret:
        return None

    return frame


def preprocess(frame):

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    return rgb


def extract_landmark(rgb):

    result = pose.process(rgb)

    if not result.pose_landmarks:
        return None

    landmark = result.pose_landmarks.landmark

    return landmark


def calculate_angle(landmark):

    # 양쪽 귀 평균
    ear_x = (landmark[7].x + landmark[8].x) / 2
    ear_y = (landmark[7].y + landmark[8].y) / 2

    # 양쪽 어깨 평균
    shoulder_x = (landmark[11].x + landmark[12].x) / 2
    shoulder_y = (landmark[11].y + landmark[12].y) / 2

    dx = ear_x - shoulder_x
    dy = shoulder_y - ear_y

    angle = math.degrees(math.atan2(dy, dx))

    return angle


def turtle_neck_detection(angle):

    # 실험하면서 수정할 값
    if angle < 70:
        return "거북목"

    elif angle < 80:
        return "주의"

    else:
        return "정상"


def save_image(frame):

    filename = datetime.now().strftime("%Y%m%d_%H%M%S.jpg")

    cv2.imwrite(filename, frame)


def output_result(angle, result):

    print("-----------------------------------")
    print("목 각도 : {:.2f}".format(angle))
    print("판단 :", result)
    print("-----------------------------------")


# ==========================
# Main
# ==========================

print("===== 시스템 시작 =====")

try:

    while True:

        print("사진 촬영...")

        frame = capture_image()

        if frame is None:
            print("사진 촬영 실패")
            continue

        rgb = preprocess(frame)

        landmark = extract_landmark(rgb)

        if landmark is None:

            print("사람을 찾지 못했습니다.")

        else:

            angle = calculate_angle(landmark)

            result = turtle_neck_detection(angle)

            output_result(angle, result)

            save_image(frame)

            # --------------------------
            # 여기에서 CSE로 결과 전달
            # send_to_CSE(angle)
            # --------------------------

            # --------------------------
            # 거북목이면 책상 제어
            # control_desk()
            # --------------------------

        print("5분 대기...\n")

        time.sleep(300)

except KeyboardInterrupt:

    print("프로그램 종료")

finally:

    cap.release()

    cv2.destroyAllWindows()