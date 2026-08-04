#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <ArduinoJson.h>

#if __has_include("arduino_secrets.h")
#include "arduino_secrets.h"
#else
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define MOBIUS_API_KEY "YOUR_MOBIUS_API_KEY"
#endif

const char MOBIUS_HOST[] = "platform.iotcoss.ac.kr";
const int MOBIUS_PORT = 443;
const char MOBIUS_ROOT_PATH[] = "/api/proxy/swagger/Mobius";

const char MOBIUS_ORIGIN[] = "S";
const char MOBIUS_LECTURE[] = "LCT_20260002";
const char MOBIUS_CREATOR[] = "sjuADDHD";

const char DEVICE_ID[] = "desk-motor-uno-r4-01";
const char AE_NAME[] = "deskMotor";
const char COMMAND_CONTAINER[] = "command";
const char STATUS_CONTAINER[] = "status";
const char EVENTS_CONTAINER[] = "motorEvents";

const uint8_t STEP_PIN = 4;
const uint8_t DIR_PIN = 5;
const uint8_t ENABLE_PIN = 6;

const bool USE_ENABLE_PIN = true;
const bool DRIVER_ENABLE_LEVEL = LOW;
const bool DRIVER_DISABLE_LEVEL = HIGH;

const bool DIR_TO_UP_LEVEL = LOW;
const bool DIR_TO_DOWN_LEVEL = HIGH;
const bool ASSUME_DOWN_ON_BOOT = true;

const float UP_HEIGHT_CM = 125.0;
const float DOWN_HEIGHT_CM = 75.0;
const float HEIGHT_THRESHOLD_CM = 100.0;

const unsigned long COMMAND_POLL_INTERVAL_MS = 1000;
const unsigned long WIFI_RETRY_INTERVAL_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 8000;

const unsigned long UP_MOVE_TIME_MS = 6300;
const unsigned long DOWN_MOVE_TIME_MS = 6300;
const unsigned int STEP_HIGH_US = 700;
const unsigned int STEP_LOW_US = 700;

enum DeskPosition {
  POSITION_UNKNOWN,
  POSITION_DOWN,
  POSITION_MOVING_UP,
  POSITION_UP,
  POSITION_MOVING_DOWN,
  POSITION_ERROR
};

WiFiSSLClient client;

DeskPosition currentPosition = POSITION_UNKNOWN;
DeskPosition targetPosition = POSITION_UNKNOWN;
bool moving = false;

unsigned long lastPollAtMs = 0;
unsigned long lastWifiAttemptAtMs = 0;
unsigned long requestCounter = 0;
bool wifiAttempted = false;

String lastCommandResourceKey = "";
String lastCommandId = "";
String activeCommandId = "";
String activeSessionId = "";

const char* positionName(DeskPosition position) {
  switch (position) {
    case POSITION_DOWN:
      return "DOWN";
    case POSITION_MOVING_UP:
      return "MOVING_UP";
    case POSITION_UP:
      return "UP";
    case POSITION_MOVING_DOWN:
      return "MOVING_DOWN";
    case POSITION_ERROR:
      return "ERROR";
    default:
      return "UNKNOWN";
  }
}

String makeRequestId() {
  requestCounter++;
  return String("desk-motor-") + String(millis()) + "-" + String(requestCounter);
}

String buildPath(const char* container) {
  return String(MOBIUS_ROOT_PATH) + "/" + AE_NAME + "/" + container;
}

void setMotorDriverEnabled(bool enabled) {
  if (!USE_ENABLE_PIN) {
    return;
  }
  digitalWrite(ENABLE_PIN, enabled ? DRIVER_ENABLE_LEVEL : DRIVER_DISABLE_LEVEL);
  Serial.println(enabled ? "Motor driver enabled" : "Motor driver disabled");
}

void manageWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  unsigned long now = millis();
  if (wifiAttempted && now - lastWifiAttemptAtMs < WIFI_RETRY_INTERVAL_MS) {
    return;
  }
  wifiAttempted = true;
  lastWifiAttemptAtMs = now;
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

String httpRequest(const char* method, const String& path, const String& body, bool createCin) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("HTTP skipped: WiFi disconnected");
    return "";
  }
  if (!client.connect(MOBIUS_HOST, MOBIUS_PORT)) {
    Serial.println("HTTPS connect failed");
    return "";
  }
  client.setTimeout(HTTP_TIMEOUT_MS);

  client.print(method);
  client.print(" ");
  client.print(path);
  client.println(" HTTP/1.1");
  client.print("Host: ");
  client.println(MOBIUS_HOST);
  client.println("Accept: application/json");
  client.println("accept: */*");
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
  unsigned long deadline = millis() + HTTP_TIMEOUT_MS;
  while (millis() < deadline) {
    while (client.available()) {
      response += (char)client.read();
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

int httpStatusCode(const String& response) {
  int firstSpace = response.indexOf(' ');
  if (firstSpace < 0 || firstSpace + 4 > response.length()) {
    return 0;
  }
  return response.substring(firstSpace + 1, firstSpace + 4).toInt();
}

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
  return headers.indexOf("transfer-encoding: chunked") >= 0;
}

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

    long chunkSize = strtol(sizeText.c_str(), nullptr, 16);
    if (chunkSize <= 0) {
      break;
    }

    int dataStart = lineEnd + 2;
    int dataEnd = dataStart + chunkSize;
    if (dataEnd > chunked.length()) {
      break;
    }

    decoded += chunked.substring(dataStart, dataEnd);
    index = dataEnd + 2;
  }
  decoded.trim();
  return decoded;
}

String normalizedBody(const String& response) {
  String body = httpBody(response);
  if (isChunkedResponse(response)) {
    return decodeChunkedBody(body);
  }
  body.trim();
  return body;
}

bool postContentInstance(const char* container, JsonDocument& content) {
  StaticJsonDocument<1024> payload;
  payload["m2m:cin"]["con"].set(content.as<JsonVariant>());

  String body;
  serializeJson(payload, body);

  String response = httpRequest("POST", buildPath(container), body, true);
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

void sendStatus(const char* state, const char* commandId = "", const char* sessionId = "", float targetHeightCm = -1.0) {
  StaticJsonDocument<768> content;
  content["device_id"] = DEVICE_ID;
  content["state"] = state;
  content["position"] = positionName(currentPosition);
  content["target_position"] = positionName(targetPosition);
  content["moving"] = moving;
  content["uptime_ms"] = millis();
  if (targetHeightCm >= 0.0) {
    content["target_height_cm"] = targetHeightCm;
  }
  if (commandId && commandId[0]) {
    content["command_id"] = commandId;
  }
  if (sessionId && sessionId[0]) {
    content["session_id"] = sessionId;
  }
  postContentInstance(STATUS_CONTAINER, content);
}

void sendMotorEvent(const char* event, const char* commandId = "", const char* sessionId = "", float targetHeightCm = -1.0) {
  StaticJsonDocument<768> content;
  content["device_id"] = DEVICE_ID;
  content["event"] = event;
  content["state"] = positionName(currentPosition);
  content["position"] = positionName(currentPosition);
  content["target_position"] = positionName(targetPosition);
  content["moving"] = moving;
  content["uptime_ms"] = millis();
  if (targetHeightCm >= 0.0) {
    content["target_height_cm"] = targetHeightCm;
  }
  if (commandId && commandId[0]) {
    content["command_id"] = commandId;
  }
  if (sessionId && sessionId[0]) {
    content["session_id"] = sessionId;
  }
  postContentInstance(EVENTS_CONTAINER, content);
}

bool latestCommand(StaticJsonDocument<1024>& commandOut, String& resourceKeyOut) {
  String response = httpRequest(
    "GET",
    buildPath(COMMAND_CONTAINER) + "/latest",
    "",
    false
  );
  int status = httpStatusCode(response);
  Serial.print("GET deskMotor/command/latest HTTP ");
  Serial.println(status);
  if (status == 404) {
    return false;
  }
  if (status < 200 || status >= 300) {
    return false;
  }

  StaticJsonDocument<2048> doc;
  DeserializationError error = deserializeJson(doc, normalizedBody(response));
  if (error) {
    Serial.print("Mobius JSON parse failed: ");
    Serial.println(error.c_str());
    return false;
  }

  JsonObject cin = doc["m2m:cin"];
  if (cin.isNull()) {
    return false;
  }

  const char* ri = cin["ri"] | "";
  const char* rn = cin["rn"] | "";
  JsonVariant con = cin["con"];
  if (con.isNull()) {
    return false;
  }

  resourceKeyOut = ri[0] ? String(ri) : String(rn);
  commandOut.clear();
  if (con.is<JsonObject>()) {
    commandOut.set(con);
  } else if (con.is<const char*>()) {
    DeserializationError conError = deserializeJson(commandOut, con.as<const char*>());
    if (conError) {
      Serial.print("Command con JSON string parse failed: ");
      Serial.println(conError.c_str());
      return false;
    }
  } else {
    return false;
  }

  if (resourceKeyOut.length() == 0) {
    const char* commandId = commandOut["command_id"] | "";
    resourceKeyOut = String(commandId);
  }
  return resourceKeyOut.length() > 0;
}

void rememberLatestCommandOnStartup() {
  StaticJsonDocument<1024> command;
  String resourceKey;
  if (!latestCommand(command, resourceKey)) {
    return;
  }

  lastCommandResourceKey = resourceKey;
  const char* commandId = command["command_id"] | "";
  if (commandId[0]) {
    lastCommandId = commandId;
  }

  Serial.print("Startup ignored stale latest command: ");
  Serial.println(resourceKey);
}

DeskPosition targetFromCommand(JsonObject command, float targetHeightCm) {
  String target = String(command["target_position"] | "");
  target.toUpperCase();
  String direction = String(command["direction"] | "");
  direction.toLowerCase();

  if (target == "UP" || direction == "up") {
    return POSITION_UP;
  }
  if (target == "DOWN" || direction == "down") {
    return POSITION_DOWN;
  }
  if (targetHeightCm >= HEIGHT_THRESHOLD_CM) {
    return POSITION_UP;
  }
  if (targetHeightCm >= 0.0) {
    return POSITION_DOWN;
  }
  return POSITION_UNKNOWN;
}

unsigned long moveDurationMs(DeskPosition requestedPosition) {
  return requestedPosition == POSITION_UP ? UP_MOVE_TIME_MS : DOWN_MOVE_TIME_MS;
}

void runTimedMotion(DeskPosition requestedPosition) {
  unsigned long durationMs = moveDurationMs(requestedPosition);
  unsigned long startedAt = millis();
  unsigned long steps = 0;

  while ((unsigned long)(millis() - startedAt) < durationMs) {
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(STEP_HIGH_US);
    digitalWrite(STEP_PIN, LOW);
    delayMicroseconds(STEP_LOW_US);
    steps++;
  }

  Serial.print("Timed motion steps=");
  Serial.print(steps);
  Serial.print(", duration_ms=");
  Serial.println(durationMs);
}

bool startMotion(DeskPosition requestedPosition, const char* commandId, const char* sessionId, float targetHeightCm) {
  if (requestedPosition != POSITION_UP && requestedPosition != POSITION_DOWN) {
    Serial.println("Invalid requested position");
    currentPosition = POSITION_ERROR;
    sendMotorEvent("movement_failed", commandId, sessionId, targetHeightCm);
    sendStatus("ERROR", commandId, sessionId, targetHeightCm);
    return false;
  }

  targetPosition = requestedPosition;
  currentPosition = requestedPosition == POSITION_UP ? POSITION_MOVING_UP : POSITION_MOVING_DOWN;
  moving = true;
  activeCommandId = commandId;
  activeSessionId = sessionId;

  setMotorDriverEnabled(true);
  delay(5);
  digitalWrite(DIR_PIN, requestedPosition == POSITION_UP ? DIR_TO_UP_LEVEL : DIR_TO_DOWN_LEVEL);

  Serial.print("Moving to ");
  Serial.println(positionName(requestedPosition));
  sendMotorEvent("movement_started", activeCommandId.c_str(), activeSessionId.c_str(), targetHeightCm);
  sendStatus(positionName(currentPosition), activeCommandId.c_str(), activeSessionId.c_str(), targetHeightCm);

  runTimedMotion(requestedPosition);

  currentPosition = targetPosition;
  moving = false;
  setMotorDriverEnabled(false);

  Serial.print("Motion complete: ");
  Serial.println(positionName(currentPosition));
  sendMotorEvent("movement_completed", activeCommandId.c_str(), activeSessionId.c_str(), targetHeightCm);
  sendStatus(positionName(currentPosition), activeCommandId.c_str(), activeSessionId.c_str(), targetHeightCm);

  activeCommandId = "";
  activeSessionId = "";
  return true;
}

void handleCommand(StaticJsonDocument<1024>& commandDoc, const String& resourceKey) {
  JsonObject command = commandDoc.as<JsonObject>();
  const char* action = command["action"] | "";
  const char* commandId = command["command_id"] | "";
  const char* sessionId = command["session_id"] | "";
  float targetHeightCm = command["target_height_cm"] | -1.0;

  if (resourceKey == lastCommandResourceKey) {
    return;
  }
  lastCommandResourceKey = resourceKey;

  if (!commandId[0]) {
    Serial.println("Ignoring command without command_id");
    sendMotorEvent("command_ignored_missing_command_id", "", sessionId, targetHeightCm);
    return;
  }

  if (String(commandId) == lastCommandId) {
    Serial.println("Ignoring duplicate command_id");
    sendMotorEvent("command_ignored_duplicate", commandId, sessionId, targetHeightCm);
    return;
  }

  if (moving || currentPosition == POSITION_MOVING_UP || currentPosition == POSITION_MOVING_DOWN) {
    Serial.println("Ignoring command while moving");
    sendMotorEvent("command_ignored_moving", commandId, sessionId, targetHeightCm);
    return;
  }

  if (String(action) != "set_height") {
    Serial.println("Ignoring unsupported command");
    sendMotorEvent("command_ignored_unsupported", commandId, sessionId, targetHeightCm);
    lastCommandId = commandId;
    return;
  }

  DeskPosition requestedPosition = targetFromCommand(command, targetHeightCm);
  if (requestedPosition == POSITION_UNKNOWN) {
    Serial.println("Ignoring command with unknown target");
    sendMotorEvent("command_ignored_unknown_target", commandId, sessionId, targetHeightCm);
    lastCommandId = commandId;
    return;
  }

  lastCommandId = commandId;

  if (requestedPosition == currentPosition) {
    Serial.println("Command target already reached");
    targetPosition = currentPosition;
    sendMotorEvent("command_noop", commandId, sessionId, targetHeightCm);
    sendStatus(positionName(currentPosition), commandId, sessionId, targetHeightCm);
    return;
  }

  sendMotorEvent("command_accepted", commandId, sessionId, targetHeightCm);
  startMotion(requestedPosition, commandId, sessionId, targetHeightCm);
}

void pollMobius() {
  if (millis() - lastPollAtMs < COMMAND_POLL_INTERVAL_MS) {
    return;
  }
  lastPollAtMs = millis();

  StaticJsonDocument<1024> command;
  String resourceKey;
  if (latestCommand(command, resourceKey)) {
    handleCommand(command, resourceKey);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  if (USE_ENABLE_PIN) {
    pinMode(ENABLE_PIN, OUTPUT);
  }
  digitalWrite(STEP_PIN, LOW);
  digitalWrite(DIR_PIN, DIR_TO_DOWN_LEVEL);
  setMotorDriverEnabled(false);

  currentPosition = ASSUME_DOWN_ON_BOOT ? POSITION_DOWN : POSITION_UNKNOWN;
  targetPosition = currentPosition;

  manageWiFi();
  unsigned long startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 10000) {
    manageWiFi();
    delay(50);
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi connected, IP=");
    Serial.println(WiFi.localIP());
    rememberLatestCommandOnStartup();
  }

  sendStatus(positionName(currentPosition));
  sendMotorEvent("startup");
}

void loop() {
  manageWiFi();
  pollMobius();
}
