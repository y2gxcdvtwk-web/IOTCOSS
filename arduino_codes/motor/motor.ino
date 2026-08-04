#include <WiFiS3.h>
#include <ArduinoJson.h>

#if __has_include("arduino_secrets.h")
#include "arduino_secrets.h"
#else
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define MOBIUS_API_KEY "YOUR_MOBIUS_API_KEY"
#endif

// ======================================================
// Wi-Fi 설정
// ======================================================

// ======================================================
// Mobius oneM2M 서버 설정
// ======================================================
const char MOBIUS_HOST[] = "platform.iotcoss.ac.kr";
const int MOBIUS_PORT = 443;
const char MOBIUS_ROOT_PATH[] = "/api/proxy/swagger/Mobius";

// Mobius 인증 헤더
const char MOBIUS_ORIGIN[] = "S";

// 보안을 위해 실제 API 키는 직접 입력
const char MOBIUS_LECTURE[] = "LCT_20260002";
const char MOBIUS_CREATOR[] = "sjuADDHD";

// ======================================================
// Arduino 장치 및 Mobius 컨테이너
// ======================================================
const char DEVICE_ID[] = "desk-motor-uno-r4-01";

const char AE_NAME[] = "deskMotor";
const char COMMAND_CONTAINER[] = "command";
const char STATUS_CONTAINER[] = "status";
const char EVENTS_CONTAINER[] = "motorEvents";

// ======================================================
// DRV8825 배선
// ======================================================
const uint8_t STEP_PIN = 4;  // Arduino D4
const uint8_t DIR_PIN = 5;   // Arduino D5

// 책상 방향
// 실제 동작이 반대라면 HIGH와 LOW를 서로 바꾸면 됨
const bool DIR_TO_STAND_LEVEL = HIGH;
const bool DIR_TO_SIT_LEVEL = LOW;

// ======================================================
// 동작 설정
// ======================================================
const unsigned long COMMAND_POLL_INTERVAL_MS = 2000;

// 5000스텝 × (HIGH 500us + LOW 500us)
// 약 5초 동안 이동
const unsigned long MOVE_STEPS = 5000;
const unsigned int STEP_HIGH_US = 500;
const unsigned int STEP_LOW_US = 500;

// ======================================================
// 책상 상태
// ======================================================
enum DeskState {
  SIT_STATE,
  STAND_STATE
};

WiFiSSLClient client;

DeskState currentState = SIT_STATE;
DeskState targetState = SIT_STATE;

bool moving = false;

unsigned long lastPollAtMs = 0;
unsigned long requestCounter = 0;

String lastCommandResourceName = "";
String lastCommandId = "";

String activeCommandId = "";
String activeSessionId = "";

bool discardFirstUnseenCommandAfterMotion = false;
unsigned long discardUnseenUntilMs = 0;

// ======================================================
// 책상 상태 문자열
// ======================================================
const char* stateName(DeskState state) {
  return state == STAND_STATE ? "STAND" : "SIT";
}

// target_height_cm에 따라 SIT 또는 STAND 결정
DeskState stateForHeight(float targetHeightCm) {
  return targetHeightCm >= 100.0 ? STAND_STATE : SIT_STATE;
}

// ======================================================
// Mobius 요청 ID 생성
// ======================================================
String makeRequestId() {
  requestCounter++;

  return String("uno-r4-")
       + String(millis())
       + "-"
       + String(requestCounter);
}

// ======================================================
// Wi-Fi 연결
// ======================================================
void connectWiFi() {
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print("Connecting to WiFi: ");
    Serial.println(WIFI_SSID);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long started = millis();

    while (
      WiFi.status() != WL_CONNECTED &&
      millis() - started < 10000
    ) {
      delay(250);
      Serial.print(".");
    }

    Serial.println();
  }

  Serial.print("WiFi connected, IP=");
  Serial.println(WiFi.localIP());
}

// ======================================================
// Mobius 경로 생성
// 예: /api/proxy/swagger/Mobius/deskMotor/status
// ======================================================
String buildPath(const char* container) {
  return String(MOBIUS_ROOT_PATH)
       + "/"
       + AE_NAME
       + "/"
       + container;
}

// ======================================================
// HTTPS 요청
// ======================================================
String httpRequest(
  const char* method,
  const String& path,
  const String& body,
  bool createCin
) {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!client.connect(MOBIUS_HOST, MOBIUS_PORT)) {
    Serial.println("HTTPS connect failed");
    return "";
  }

  client.print(method);
  client.print(" ");
  client.print(path);
  client.println(" HTTP/1.1");

  client.print("Host: ");
  client.println(MOBIUS_HOST);

  client.println("Accept: application/json");

  client.print("X-M2M-Origin: ");
  client.println(MOBIUS_ORIGIN);

  client.print("X-M2M-RI: ");
  client.println(makeRequestId());

  client.print("X-API-KEY: ");
  client.println(MOBIUS_API_KEY);

  client.print("X-AUTH-CUSTOM-LECTURE: ");
  client.println(MOBIUS_LECTURE);

  client.print("X-AUTH-CUSTOM-CREATOR: ");
  client.println(MOBIUS_CREATOR);

  if (createCin) {
    client.println("Content-Type: application/json;ty=4");

    client.print("Content-Length: ");
    client.println(body.length());
  }

  client.println("Connection: close");
  client.println();

  if (createCin) {
    client.print(body);
  }

  String response;

  unsigned long deadline = millis() + 8000;

  while (millis() < deadline) {
    while (client.available()) {
      char c = client.read();
      response += c;

      // 응답이 계속 들어오면 타임아웃 연장
      deadline = millis() + 1000;
    }

    if (!client.connected()) {
      break;
    }

    delay(1);
  }

  client.stop();

  return response;
}

// ======================================================
// HTTP 상태 코드 추출
// ======================================================
int httpStatusCode(const String& response) {
  int firstSpace = response.indexOf(' ');

  if (
    firstSpace < 0 ||
    firstSpace + 4 > response.length()
  ) {
    return 0;
  }

  return response
    .substring(firstSpace + 1, firstSpace + 4)
    .toInt();
}

// ======================================================
// HTTP Body 추출
// ======================================================
String httpBody(const String& response) {
  int bodyIndex = response.indexOf("\r\n\r\n");
  int separatorLength = 4;

  if (bodyIndex < 0) {
    bodyIndex = response.indexOf("\n\n");
    separatorLength = 2;
  }

  if (bodyIndex < 0) {
    return "";
  }

  return response.substring(bodyIndex + separatorLength);
}

// ======================================================
// Chunked 응답 확인
// ======================================================
bool isChunkedResponse(const String& response) {
  int headerEnd = response.indexOf("\r\n\r\n");

  if (headerEnd < 0) {
    headerEnd = response.indexOf("\n\n");
  }

  if (headerEnd < 0) {
    return false;
  }

  String headers = response.substring(0, headerEnd);
  headers.toLowerCase();

  return headers.indexOf(
    "transfer-encoding: chunked"
  ) >= 0;
}

// ======================================================
// Chunked Body 디코딩
// ======================================================
String decodeChunkedBody(const String& chunked) {
  String decoded;
  int index = 0;

  while (index < chunked.length()) {
    int lineEnd = chunked.indexOf("\r\n", index);

    if (lineEnd < 0) {
      break;
    }

    String sizeText = chunked.substring(index, lineEnd);

    int semicolon = sizeText.indexOf(';');

    if (semicolon >= 0) {
      sizeText = sizeText.substring(0, semicolon);
    }

    sizeText.trim();

    long chunkSize = strtol(
      sizeText.c_str(),
      nullptr,
      16
    );

    if (chunkSize <= 0) {
      break;
    }

    int dataStart = lineEnd + 2;
    int dataEnd = dataStart + chunkSize;

    if (dataEnd > chunked.length()) {
      break;
    }

    decoded += chunked.substring(
      dataStart,
      dataEnd
    );

    index = dataEnd + 2;
  }

  return decoded;
}

// ======================================================
// 최종 HTTP Body 반환
// ======================================================
String normalizedBody(const String& response) {
  String body = httpBody(response);

  if (isChunkedResponse(response)) {
    return decodeChunkedBody(body);
  }

  body.trim();

  return body;
}

// ======================================================
// Mobius Content Instance POST
// ======================================================
bool postContentInstance(
  const char* container,
  JsonDocument& content
) {
  StaticJsonDocument<768> payload;

  payload["m2m:cin"]["con"].set(
    content.as<JsonVariant>()
  );

  String body;
  serializeJson(payload, body);

  String response = httpRequest(
    "POST",
    buildPath(container),
    body,
    true
  );

  int status = httpStatusCode(response);

  if (status >= 200 && status < 300) {
    return true;
  }

  Serial.print("POST ");
  Serial.print(container);
  Serial.print(" failed, HTTP ");
  Serial.println(status);

  return false;
}

// ======================================================
// 책상 상태 서버 전송
// ======================================================
void sendStatus(
  const char* state,
  const char* commandId = "",
  const char* sessionId = ""
) {
  StaticJsonDocument<512> content;

  content["device_id"] = DEVICE_ID;
  content["state"] = state;

  content["desk_state"] = stateName(currentState);
  content["target_state"] = stateName(targetState);

  content["moving"] = moving;
  content["uptime_ms"] = millis();

  if (commandId && commandId[0]) {
    content["command_id"] = commandId;
  }

  if (sessionId && sessionId[0]) {
    content["session_id"] = sessionId;
  }

  postContentInstance(
    STATUS_CONTAINER,
    content
  );
}

// ======================================================
// 모터 이벤트 서버 전송
// ======================================================
void sendMotorEvent(
  const char* event,
  const char* commandId = "",
  const char* sessionId = ""
) {
  StaticJsonDocument<512> content;

  content["device_id"] = DEVICE_ID;
  content["event"] = event;

  content["desk_state"] = stateName(currentState);
  content["target_state"] = stateName(targetState);

  content["moving"] = moving;
  content["uptime_ms"] = millis();

  if (commandId && commandId[0]) {
    content["command_id"] = commandId;
  }

  if (sessionId && sessionId[0]) {
    content["session_id"] = sessionId;
  }

  postContentInstance(
    EVENTS_CONTAINER,
    content
  );
}

// ======================================================
// Mobius 최신 명령 읽기
// ======================================================
bool latestCommand(
  JsonDocument& commandOut,
  String& resourceNameOut
) {
  String path =
    buildPath(COMMAND_CONTAINER)
    + "/latest";

  String response = httpRequest(
    "GET",
    path,
    "",
    false
  );

  int status = httpStatusCode(response);

  if (status == 404) {
    return false;
  }

  if (status < 200 || status >= 300) {
    Serial.print("GET latest failed, HTTP ");
    Serial.println(status);

    return false;
  }

  StaticJsonDocument<1536> doc;

  String body = normalizedBody(response);

  DeserializationError error =
    deserializeJson(doc, body);

  if (error) {
    Serial.print("Mobius JSON parse failed: ");
    Serial.println(error.c_str());

    return false;
  }

  JsonObject cin = doc["m2m:cin"];

  if (cin.isNull()) {
    return false;
  }

  const char* rn = cin["rn"] | "";
  JsonVariant con = cin["con"];

  if (
    !rn[0] ||
    con.isNull() ||
    !con.is<JsonObject>()
  ) {
    return false;
  }

  resourceNameOut = rn;

  commandOut.clear();
  commandOut.set(con);

  return true;
}

// ======================================================
// 부팅 시 기존 /latest 명령 기억
//
// 전원을 다시 켰을 때 Mobius에 남아 있는 예전 명령으로
// 책상이 갑자기 움직이지 않도록 함
// ======================================================
void rememberLatestCommandOnStartup() {
  StaticJsonDocument<768> command;
  String resourceName;

  if (!latestCommand(command, resourceName)) {
    return;
  }

  lastCommandResourceName = resourceName;

  const char* commandId =
    command["command_id"] | "";

  if (commandId[0]) {
    lastCommandId = commandId;
  }

  Serial.print(
    "Startup ignored stale latest command: "
  );
  Serial.println(resourceName);
}

// ======================================================
// 모터 고정 스텝 이동
// ======================================================
void runFixedStepMotion() {
  for (
    unsigned long step = 0;
    step < MOVE_STEPS;
    step++
  ) {
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(STEP_HIGH_US);

    digitalWrite(STEP_PIN, LOW);
    delayMicroseconds(STEP_LOW_US);
  }
}

// ======================================================
// 모터 이동 시작
// ======================================================
void startMotion(
  DeskState requestedState,
  const char* commandId,
  const char* sessionId
) {
  targetState = requestedState;
  moving = true;

  activeCommandId = commandId;
  activeSessionId = sessionId;

  bool directionLevel =
    requestedState == STAND_STATE
      ? DIR_TO_STAND_LEVEL
      : DIR_TO_SIT_LEVEL;

  digitalWrite(DIR_PIN, directionLevel);

  // DIR 변경 후 STEP 시작 전 안정화 시간
  delayMicroseconds(20);

  Serial.print("Moving to ");
  Serial.println(stateName(requestedState));

  // 이동 시작 상태 서버 전송
  sendMotorEvent(
    "movement_started",
    activeCommandId.c_str(),
    activeSessionId.c_str()
  );

  sendStatus(
    "moving",
    activeCommandId.c_str(),
    activeSessionId.c_str()
  );

  // 정확히 5000스텝 이동
  runFixedStepMotion();

  // 실제 책상 상태 갱신
  currentState = targetState;
  moving = false;

  discardFirstUnseenCommandAfterMotion = true;
  discardUnseenUntilMs =
    millis() + COMMAND_POLL_INTERVAL_MS;

  Serial.print("Motion complete: ");
  Serial.println(stateName(currentState));

  // 이동 완료 이벤트 및 최종 상태 서버 전송
  sendMotorEvent(
    "movement_completed",
    activeCommandId.c_str(),
    activeSessionId.c_str()
  );

  sendStatus(
    "online",
    activeCommandId.c_str(),
    activeSessionId.c_str()
  );

  activeCommandId = "";
  activeSessionId = "";
}

// ======================================================
// 수신 명령 처리
// ======================================================
void handleCommand(
  JsonDocument& command,
  const String& resourceName
) {
  const char* action =
    command["action"] | "";

  const char* commandId =
    command["command_id"] | "";

  const char* sessionId =
    command["session_id"] | "";

  float targetHeightCm =
    command["target_height_cm"] | -1.0;

  // 동일한 Mobius CIN이면 무시
  if (resourceName == lastCommandResourceName) {
    return;
  }

  lastCommandResourceName = resourceName;

  // 모터 이동 직후 발견되는 명령 보호
  if (
    discardFirstUnseenCommandAfterMotion &&
    millis() <= discardUnseenUntilMs
  ) {
    discardFirstUnseenCommandAfterMotion = false;

    Serial.println(
      "Ignoring command observed immediately after motion"
    );

    sendMotorEvent(
      "command_ignored_moving",
      commandId,
      sessionId
    );

    return;
  }

  discardFirstUnseenCommandAfterMotion = false;

  // command_id가 없으면 무시
  if (!commandId[0]) {
    Serial.println(
      "Ignoring command without command_id"
    );

    sendMotorEvent(
      "command_ignored_missing_command_id",
      "",
      sessionId
    );

    return;
  }

  // 동일 command_id 중복 실행 방지
  if (String(commandId) == lastCommandId) {
    Serial.println(
      "Ignoring duplicate command_id"
    );

    sendMotorEvent(
      "command_ignored_duplicate",
      commandId,
      sessionId
    );

    return;
  }

  // 이동 중 들어온 명령은 무시
  if (moving) {
    Serial.println(
      "Ignoring command while moving"
    );

    sendMotorEvent(
      "command_ignored_moving",
      commandId,
      sessionId
    );

    return;
  }

  // set_height 명령만 처리
  if (
    String(action) != "set_height" ||
    targetHeightCm < 0.0
  ) {
    Serial.println(
      "Ignoring unsupported command"
    );

    sendMotorEvent(
      "command_ignored_unsupported",
      commandId,
      sessionId
    );

    lastCommandId = commandId;

    return;
  }

  DeskState requestedState =
    stateForHeight(targetHeightCm);

  lastCommandId = commandId;

  // 이미 요청한 상태라면 모터를 움직이지 않음
  if (requestedState == currentState) {
    Serial.println(
      "Command target already reached"
    );

    targetState = currentState;

    sendMotorEvent(
      "command_noop",
      commandId,
      sessionId
    );

    sendStatus(
      "online",
      commandId,
      sessionId
    );

    return;
  }

  sendMotorEvent(
    "command_accepted",
    commandId,
    sessionId
  );

  startMotion(
    requestedState,
    commandId,
    sessionId
  );
}

// ======================================================
// Mobius 명령 Polling
// ======================================================
void pollMobius() {
  if (
    millis() - lastPollAtMs
    < COMMAND_POLL_INTERVAL_MS
  ) {
    return;
  }

  lastPollAtMs = millis();

  StaticJsonDocument<768> command;
  String resourceName;

  if (latestCommand(command, resourceName)) {
    handleCommand(command, resourceName);
  }
}

// ======================================================
// Arduino 초기화
// ======================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);

  digitalWrite(STEP_PIN, LOW);
  digitalWrite(DIR_PIN, DIR_TO_SIT_LEVEL);

  // 실제 시작 위치가 앉은 높이라고 가정
  currentState = SIT_STATE;
  targetState = SIT_STATE;

  connectWiFi();

  // 서버에 남아 있는 이전 명령은 실행하지 않고 기억만 함
  rememberLatestCommandOnStartup();

  // 시작 상태 서버 전송
  sendStatus("online");
  sendMotorEvent("startup");

  Serial.println("Desk motor controller ready");
  Serial.println("Current state: SIT");
}

// ======================================================
// 메인 반복
// ======================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  pollMobius();
}
