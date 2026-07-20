# IOTCOSS

아두이노, Raspberry Pi 4, USB 카메라와 Mobius oneM2M을 연결해 자세를 분석하고
스마트 데스크 피드백을 제공하는 프로젝트입니다.

## 시스템 구성

1. Raspberry Pi가 카메라 영상에서 자세 특징을 추출합니다.
2. 로컬에서 정상 자세, 거북목 등의 상태를 판정합니다.
3. 판정 결과를 `postureCamera` AE에 `m2m:cin`으로 저장합니다.
4. `analyticsServer` FastAPI가 SUB 알림, 세션, AI 분석과 앱 API를 담당합니다.
5. Arduino가 전달받은 상태에 따라 데스크, 조명, 부저를 제어합니다.

## FastAPI Mobius AI Gateway

### 실행

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

- UI: http://localhost:8000
- OpenAPI: http://localhost:8000/docs
- 상태 확인: http://localhost:8000/health

Mobius 설정과 인증정보는 `.env`에서 관리합니다. `MOBIUS_NOTIFICATION_URI`에는
Mobius가 접근할 수 있는 `/api/v1/mobius/notifications` 공개 주소를 설정합니다.

### 확정 Mobius 구조

- `postureCamera`: `command`, `status`, `postureSamples`, `postureEvents`
- `deskInterface`: `lcdCommand`, `buttonEvents`, `status`
- `deskMotor`: `command`, `status`, `motorEvents`
- `postureLight`: `command`, `status`, `lightEvents`
- `analyticsServer`: `status`, `sessionEvents`, `currentSession`, `suggestions`, `sessionSummaries`

서버 시작 시 `MOBIUS_AUTO_REGISTER=true`이면 자신이 소유하는 `analyticsServer`
AE/CNT만 확인하고 누락된 리소스를 생성합니다. 장치 AE/CNT는 존재 여부만 확인하며
생성하거나 변경하지 않습니다. `MOBIUS_NOTIFICATION_URI`가 설정된 경우 장치의
`status`와 이벤트/샘플 컨테이너에 `subToAnalyticsServer` 구독을 확인하고 생성합니다.
command 계열은 장치가 `/latest`를 polling하므로 구독을 만들지 않습니다.

AI는 기본적으로 외부 서비스 없이 로컬 분석을 사용합니다. OpenAI 연동 시
`AI_PROVIDER=openai`와 `OPENAI_API_KEY`를 설정합니다.

### 앱 API

- `POST /api/v1/sessions`: 세션 생성
- `GET/DELETE /api/v1/sessions/{id}`: 세션 조회/종료
- `POST/GET /api/v1/sessions/{id}/events`: 이벤트 저장/조회
- `POST /api/v1/sessions/{id}/analysis`: 세션 AI 분석
- `WS /api/v1/ws/sessions/{id}`: 실시간 이벤트
- `POST /api/v1/mobius/ingest`: Mobius 알림 수신
- `POST /api/v1/mobius/notifications`: oneM2M SUB 알림 수신
- `POST /api/v1/devices/{device}/commands`: 장치 명령 CIN 생성

명령 API의 `{device}`는 `posture-camera`, `desk-interface`, `desk-motor`,
`posture-light` 중 하나입니다.

## 디렉터리

- `app/`: FastAPI 서버, Mobius 어댑터, 세션/AI 분석, 웹 UI
- `raspberry_pi_codes/`: 카메라 및 자세 분석 코드
- `arduino_codes/`: 데스크와 피드백 장치 코드
- `tests/`: FastAPI 통합 테스트

## Raspberry Pi 자세 카메라 실행

`raspberry_pi_codes/pose2.py`는 시작할 때 FastAPI 세션을 생성하고, 해당
`session_id`를 모든 Mobius 데이터에 포함합니다.

```bash
export APP_BASE_URL="http://<FastAPI서버IP>:8000"
export DEVICE_ID="posture-camera-01"
export MOBIUS_ROOT="https://platform.iotcoss.ac.kr/api/proxy/swagger/Mobius"
export MOBIUS_ORIGIN="S"
export MOBIUS_API_KEY="<API key>"
export MOBIUS_LECTURE="<lecture id>"
export MOBIUS_CREATOR="<creator id>"

# 선택 설정
export SAMPLE_UPLOAD_INTERVAL="1.0"
export COMMAND_POLL_INTERVAL="2.0"
export REQUEST_TIMEOUT="5.0"

python3 raspberry_pi_codes/pose2.py
```

데이터 흐름:

- 시작/종료 상태 → `postureCamera/status`
- 주기 측정값 → `postureCamera/postureSamples`
- 거북목 감지/회복 전환 → `postureCamera/postureEvents`
- 제어 명령 polling → `postureCamera/command/latest`
- 앱 세션 시작/종료 → FastAPI `/api/v1/sessions`

FastAPI가 다른 PC에서 실행 중이면 방화벽에서 TCP 8000 포트를 허용하고
`APP_BASE_URL`에 `localhost`가 아닌 해당 PC의 내부 IP를 사용해야 합니다.
