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

## Cloudflare Tunnel 공개 운영

Mobius SUB의 `nu`는 Mobius CSE가 접근할 수 있는 공개 HTTPS 주소여야 합니다.
고정 SUB 주소를 위해 Cloudflare 계정과 Cloudflare DNS에 연결된 도메인을 사용하는
named tunnel을 권장합니다.

### 1. cloudflared 설치 및 로그인

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login
```

### 2. 고정 터널 생성

```powershell
cloudflared tunnel create addhd-analytics
cloudflared tunnel list
cloudflared tunnel route dns addhd-analytics analytics.<YOUR-DOMAIN>
```

생성 결과의 Tunnel UUID를 확인한 후
`cloudflare/config.yml.example`을 `%USERPROFILE%\.cloudflared\config.yml`로 복사하고
UUID, Windows 사용자명, 도메인을 실제 값으로 바꿉니다.

```powershell
cloudflared tunnel ingress validate
cloudflared tunnel run addhd-analytics
```

Cloudflare Dashboard 방식으로 만들었다면 Public Hostname의 Service URL을
`http://localhost:8000`으로 설정하고 화면에 표시된 token 명령으로 실행해도 됩니다.

### 3. FastAPI 공개 알림 주소 설정

프로젝트 폴더에서 다음 스크립트를 실행합니다.

```powershell
.\scripts\set_public_url.ps1 -PublicUrl "https://analytics.<YOUR-DOMAIN>"
```

설정되는 값:

```env
MOBIUS_NOTIFICATION_URI=https://analytics.<YOUR-DOMAIN>/api/v1/mobius/notifications
MOBIUS_AUTO_REGISTER=true
MOBIUS_SYNC_ON_STARTUP=true
```

FastAPI를 재시작하면 서버가 9개 `subToAnalyticsServer` SUB를 확인합니다. SUB가
없으면 서버 준비 완료 후 생성하고, 기존 SUB의 `nu`가 다른 주소이면 현재 공개
주소로 갱신합니다. 자동 등록에 실패한 경우 다음 요청으로 재시도합니다.

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/v1/admin/reconcile-subscriptions
```

### 4. 공개 연결 및 동기화 확인

```powershell
Invoke-RestMethod https://analytics.<YOUR-DOMAIN>/health
Invoke-RestMethod `
  -Method Post `
  -Uri https://analytics.<YOUR-DOMAIN>/api/v1/admin/sync-from-ae
```

`/health`의 `ae_sync.state`가 `ok`이면 `analyticsServer` AE에서 SQLite 조회 캐시를
복원한 상태입니다.

### 임시 Quick Tunnel

도메인 없이 단기 테스트할 때만 사용합니다.

```powershell
cloudflared tunnel --url http://localhost:8000
.\scripts\set_public_url.ps1 -PublicUrl "https://발급주소.trycloudflare.com"
```

Quick Tunnel 주소는 재시작할 때 바뀌므로 주소를 다시 설정하고 FastAPI도 재시작해야
합니다. 고정 SUB를 운영할 때는 named tunnel을 사용합니다.

### AE 원본 및 SQLite 캐시

- `analyticsServer/currentSession`: 세션 상태 스냅샷
- `analyticsServer/sessionEvents`: 장치 알림을 포함한 세션 이벤트 원본
- `analyticsServer/suggestions`: AI 분석 결과
- `analyticsServer/sessionSummaries`: 종료 세션 스냅샷
- SQLite `data/app.db`: 웹 UI와 WebSocket을 위한 재구성 가능한 로컬 조회 캐시

서버 시작 시 또는 `POST /api/v1/admin/sync-from-ae` 호출 시 AE의 CIN을 읽어 SQLite를
upsert합니다. SQLite가 삭제되어도 AE 데이터로 세션 목록과 타임라인을 복원할 수
있도록 설계되어 있습니다.
