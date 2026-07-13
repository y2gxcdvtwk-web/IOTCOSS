from picamera2 import Picamera2
import cv2
import time

# ==========================
# Picamera2 초기화
# ==========================
picam2 = Picamera2()

config = picam2.create_preview_configuration(
    main={
        "size": (640, 480),
        "format": "RGB888"
    }
)

picam2.configure(config)

print("camera start...")
picam2.start()

# 카메라 안정화
time.sleep(2)

frame_count = 0

try:
    while True:
        # 프레임 획득
        print("before capture")
        frame = picam2.capture_array()
        print("after capture")
        frame_count += 1

        # 30프레임마다 출력
        if frame_count % 30 == 0:
            print(f"Frame : {frame_count}")

        # -----------------------------
        # 색이 정상이라면 아래 줄은 주석 처리하세요.
        # 색이 파랗다면 주석을 해제하세요.
        # -----------------------------
        # frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        cv2.putText(
            frame,
            f"Frame: {frame_count}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2
        )

        cv2.imshow("Picamera2 Test", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break

except KeyboardInterrupt:
    print("end")

finally:
    picam2.stop()
    cv2.destroyAllWindows()