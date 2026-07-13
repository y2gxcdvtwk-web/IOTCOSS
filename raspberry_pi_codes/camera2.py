import cv2

cap = cv2.VideoCapture(0)

print("Opened:", cap.isOpened())

ret, frame = cap.read()

print("Ret:", ret)

cap.release()
