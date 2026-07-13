from picamera2 import Picamera2
import cv2
import time

# Picamera2 초기화
picam2 = Picamera2()

# 카메라 설정
config = picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}
)

picam2.configure(config)

# 카메라 시작
picam2.start()
time.sleep(2)   # 카메라 안정화

while True:
    # 프레임 가져오기
    frame = picam2.capture_array()

    # OpenCV는 BGR을 사용하므로 변환
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    cv2.imshow("Camera", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
picam2.stop()