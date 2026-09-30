# AI 메이커톤 IoT 스마트 책상 — 담당 업무

이 문서는 [ADDHD-IOTCOSS/IOTCOSS](https://github.com/ADDHD-IOTCOSS/IOTCOSS) 팀 프로젝트에서 제가 담당한 부분을 정리한 것입니다. 프로젝트의 전체 설계, 코드 및 제작 결과물은 여러 팀원이 함께 완성했습니다.

## 프로젝트

카메라 기반 자세 분석, 아두이노 제어부, 높이조절 스텝모터, Raspberry Pi, Mobius oneM2M 서버를 연동한 스마트 책상입니다. 자세에 따른 피드백과 책상 높이조절 기능을 구현했습니다.

## 제 담당 업무

- **아두이노 전반:** 아두이노 제어부와 주변 하드웨어의 구성, 연결 및 동작 점검
- **스텝모터:** 모터 드라이버 교체를 포함한 스텝모터 구동부 작업과 동작 확인
- **하드웨어 제작:** 실제 책상 구조물과 구동부 제작·조립
- **최종 서버 점검:** 발표 전 서버 연동 및 전체 시스템의 최종 동작 확인

## 관련 코드와 자료

- [`arduino_codes/`](./arduino_codes/): 아두이노 코드
- [`desk_motor_controller_uno_r4_wifi.ino`](./desk_motor_controller_uno_r4_wifi.ino): 모터 제어 코드
- [`raspberry_pi_codes/`](./raspberry_pi_codes/): Raspberry Pi 및 자세 분석 코드
- [`README.md`](./README.md): 시스템 구조와 실행·배선 안내

이 저장소는 원본 팀 저장소의 포크입니다. 팀원들의 작업과 커밋 기록은 원본 저장소 및 이 포크의 기록에서 확인할 수 있습니다.
