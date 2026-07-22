from picamera2 import Picamera2
import cv2
import time
import os

# Picamera2 초기화
picam2 = Picamera2()

config = picam2.create_still_configuration(
    main={"size": (640, 480)}
)

picam2.configure(config)

print("camera start...")
picam2.start()

time.sleep(2)

frame_count = 0

try:
    while True:
        filename = "temp.jpg"

        print("before capture")

        picam2.capture_file(filename)

        print("after capture")

        frame = cv2.imread(filename)

        if frame is None:
            print("read faile")
            continue

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

        cv2.imshow("Picamera2 File Test", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        time.sleep(1)

except KeyboardInterrupt:
    print("end")

finally:
    picam2.stop()
    cv2.destroyAllWindows()

    if os.path.exists("temp.jpg"):
        os.remove("temp.jpg")