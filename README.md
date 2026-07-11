# IOTCOSS
아두이노+라즈베리파이4
USB Camera
      │
      ▼
영상 입력(OpenCV)
      │
      ▼
MediaPipe
 ├── Face Mesh (468 landmarks)
 ├── Face Detection
 └── Pose (33 landmarks)
      │
      ▼
특징(feature) 추출
 ├── 얼굴 방향
 ├── 눈 깜빡임   ###
 ├── 하품
 ├── 시선 방향
 ├── 머리 기울기
 ├── 목 각도   ###
 ├── 어깨 위치
 └── 몸 기울기
      │
      ▼
집중도 점수 계산
자세 점수 계산
      │
      ▼
Robot 피드백


목 각도 측정의 경우 연직 위 방향과 목의 방향의 차이로 구현