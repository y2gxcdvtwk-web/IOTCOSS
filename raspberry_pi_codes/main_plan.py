def System_Init():

def Session():
    while !End Button:
        wait(1000);
        Capture Image()#picamera2
        Image Preprocessing()#YOLO11n-pose
        CSE Analysis()
        Save Result()#json에 저장
        Control Desk()#상태값 보내면 아두이노에서 값 따라 행동

def main():
    System_Init()
    while 1:
        if Start_Button:
            Session()
        analysis()
        announcement()