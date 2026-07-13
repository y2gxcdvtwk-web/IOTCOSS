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
        # "format": "RGB888"
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
        print("before capture")

        frame = picam2.capture_array()

        print("after capture")

        frame_count += 1

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

        print(f"Displayed Frame {frame_count}")

        # q를 누르면 종료
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        # 1초 대기
        time.sleep(1)

except KeyboardInterrupt:
    print("end")

finally:
    picam2.stop()
    cv2.destroyAllWindows()