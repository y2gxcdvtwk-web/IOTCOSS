#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>

//==================================================
// Network
//==================================================

char ssid[] = "ADDHD";
char pass[] = "PASSWORD";

const char MOBIUS_HOST[] = "platform.iotcoss.ac.kr";
const int MOBIUS_PORT = 443;
const char MOBIUS_BASE_PATH[] = "/api/proxy/swagger/Mobius";

const char API_KEY[] = "REDACTED_MOBIUS_API_KEY_00000000";
const char CUSTOM_LECTURE[] = "LCT_20260002";
const char CUSTOM_CREATOR[] = "sjuADDHD";

const char DEVICE_ID[] = "desk-interface-01";

//==================================================
// Hardware
//==================================================

const byte BTN_KICKOFF_PIN = 2;
const byte BTN_ACCEPT_PIN = 3;

LiquidCrystal_I2C lcd(0x27,16,2);

//==================================================
// Session
//==================================================

String currentSessionId="";
String currentSuggestionId="";
String lastCommandId="";

long bootId=0;
unsigned long seqNumber=1;

//==================================================
// Polling
//==================================================

unsigned long lastPollTime=0;
unsigned long pollInterval=5000;

//==================================================
// Button Event
//==================================================

volatile bool kickoffPressed=false;
volatile bool acceptPressed=false;

volatile unsigned long lastKickoffInterrupt=0;
volatile unsigned long lastAcceptInterrupt=0;

const unsigned long debounceTime=150;

//==================================================
// LCD
//==================================================

String lcdLine1="";
String lcdLine2="";

String prevLine1 = "";
String prevLine2 = "";

bool hasActiveSuggestion=false;

//==================================================
// State Machine
//==================================================

enum SystemState{
    STATE_IDLE,

    STATE_WAIT_SESSION,

    STATE_SESSION_RUNNING,

    STATE_WAIT_ACCEPT,

    STATE_NETWORK_ERROR
};

SystemState systemState=STATE_IDLE;

//==================================================
// Interrupt
//==================================================

void kickoffISR(){
    unsigned long now=millis();

    if(now-lastKickoffInterrupt>debounceTime)
    {
        kickoffPressed=true;
        lastKickoffInterrupt=now;
    }
}

void acceptISR(){
    unsigned long now=millis();

    if(now-lastAcceptInterrupt>debounceTime)
    {
        acceptPressed=true;
        lastAcceptInterrupt=now;
    }
}

//==================================================
// Prototype
//==================================================

void connectWiFi();

bool sendButtonEvent(const char* button);

bool pollLcdCommand();

void updateLCD();

String generateEventId();

//==================================================
// Setup
//==================================================

void setup(){
    Serial.begin(115200);

    pinMode(BTN_KICKOFF_PIN,INPUT_PULLUP);
    pinMode(BTN_ACCEPT_PIN,INPUT_PULLUP);

    attachInterrupt(
        digitalPinToInterrupt(BTN_KICKOFF_PIN),
        kickoffISR,
        FALLING);

    attachInterrupt(
        digitalPinToInterrupt(BTN_ACCEPT_PIN),
        acceptISR,
        FALLING);

    lcd.init();
    lcd.backlight();

    lcd.setCursor(0,0);
    lcd.print("Connecting...");

    connectWiFi();

    randomSeed(analogRead(A0));

    bootId=random(100000,999999);

    lcd.clear();

    lcd.print("Press A Start");

    Serial.println("System Ready");
}

//==================================================
// Main Loop
//==================================================

void loop(){
    if(WiFi.status()!=WL_CONNECTED)
    {
        connectWiFi();
    }

    switch(systemState)
    {

    //------------------------------------------------
    // IDLE
    //------------------------------------------------

    case STATE_IDLE:

        if(kickoffPressed)
        {
            kickoffPressed=false;

            Serial.println("Kickoff Button");

            if(sendButtonEvent("KICKOFF"))
            {
                systemState=STATE_WAIT_SESSION;
                lcdLine1 = "Starting...";
                lcdLine2 = "";
                updateLCD();
            }
            else
            {
                systemState=STATE_NETWORK_ERROR;
            }
        }

        break;

    //------------------------------------------------
    // WAIT SESSION
    //------------------------------------------------

    case STATE_WAIT_SESSION:

        if(millis()-lastPollTime>pollInterval)
        {
            lastPollTime=millis();

            if(pollLcdCommand())
            {
                if(currentSessionId.length()>0)
                {
                    systemState=STATE_SESSION_RUNNING;
                }
            }
        }

        break;

    //------------------------------------------------
    // SESSION
    //------------------------------------------------

    case STATE_SESSION_RUNNING:

        if(millis()-lastPollTime>pollInterval)
        {
            lastPollTime=millis();

            pollLcdCommand();
        }

        if(hasActiveSuggestion && acceptPressed)
        {
            acceptPressed=false;

            if(sendButtonEvent("ACCEPT"))
            {
                Serial.println("Accept Sent");
            }
        }

        break;

    //------------------------------------------------
    // ERROR
    //------------------------------------------------

    case STATE_NETWORK_ERROR:
        lcdLine1 = "Network Error";
        lcdLine2 = "Retrying...";
        updateLCD();
        delay(2000);

        connectWiFi();

        systemState=STATE_IDLE;

        break;
    }

    updateLCD();
}//==================================================
// WiFi
//==================================================

void connectWiFi(){
    if (WiFi.status() == WL_CONNECTED)
        return;

    Serial.println("Connecting WiFi...");

    while (WiFi.begin(ssid, pass) != WL_CONNECTED)
    {
        Serial.println("Retry...");
        delay(3000);
    }

    Serial.println("WiFi Connected");
    Serial.print("IP : ");
    Serial.println(WiFi.localIP());

    lcd.clear();
    lcd.print("WiFi Connected");

    delay(500);
}

//==================================================
// Event ID
//==================================================

String generateEventId(){
    char buf[64];

    snprintf(
        buf,
        sizeof(buf),
        "%s-%ld-%06lu",
        DEVICE_ID,
        bootId,
        seqNumber++
    );

    return String(buf);
}

//==================================================
// POST Button Event
//==================================================

bool sendButtonEvent(const char* button){
    WiFiSSLClient client;

    Serial.println("--------------------");
    Serial.println("POST Button Event");

    if (!client.connect(MOBIUS_HOST, MOBIUS_PORT))
    {
        Serial.println("SSL Connect Failed");
        return false;
    }

    client.setTimeout(3000);

    StaticJsonDocument<512> doc;

    JsonObject cin = doc.createNestedObject("m2m:cin");
    JsonObject con = cin.createNestedObject("con");

    con["schemaVersion"] = "1.0";
    con["eventId"] = generateEventId();
    con["deviceId"] = DEVICE_ID;

    if (currentSessionId.length() > 0)
        con["sessionId"] = currentSessionId;

    con["button"] = button;

    if (strcmp(button, "ACCEPT") == 0 &&
        currentSuggestionId.length() > 0)
    {
        con["suggestionId"] = currentSuggestionId;
    }

    con["pressedAt"] = nullptr;
    con["uptimeMs"] = millis();

    String body;
    serializeJson(doc, body);

    String url =
        String(MOBIUS_BASE_PATH)
        + "/deskInterface/buttonEvents";

    client.println("POST " + url + " HTTP/1.1");
    client.println("Host: " + String(MOBIUS_HOST));
    client.println("Accept: application/json");
    client.println("Content-Type: application/json;ty=4");

    client.println(
        "X-M2M-RI: "
        + String(DEVICE_ID)
        + "-"
        + String(millis())
    );

    client.println("X-M2M-Origin: S");

    client.println(
        "X-API-KEY: "
        + String(API_KEY)
    );

    client.println(
        "X-AUTH-CUSTOM-LECTURE: "
        + String(CUSTOM_LECTURE)
    );

    client.println(
        "X-AUTH-CUSTOM-CREATOR: "
        + String(CUSTOM_CREATOR)
    );

    client.print("Content-Length: ");
    client.println(body.length());

    client.println("Connection: close");
    client.println();

    client.print(body);

    //--------------------------------------------------
    // HTTP Status
    //--------------------------------------------------

    String status = client.readStringUntil('\n');

    Serial.print("Status : ");
    Serial.println(status);

    bool success =
        status.indexOf("201") >= 0 ||
        status.indexOf("200") >= 0;

    //--------------------------------------------------
    // Skip Header
    //--------------------------------------------------

    while (client.connected())
    {
        String line = client.readStringUntil('\n');

        if (line == "\r")
            break;
    }

    //--------------------------------------------------
    // Read Body
    //--------------------------------------------------

    String response;

    response.reserve(512);

    while (client.available())
    {
        response += client.readString();
    }

    Serial.println(response);

    client.stop();

    if (success)
    {
        Serial.println("POST Success");
    }
    else
    {
        Serial.println("POST Failed");
    }

    return success;
}
void updateLCD(){
    // 첫 번째 줄 갱신
    if (lcdLine1 != prevLine1)
    {
        lcd.setCursor(0, 0);

        String text = lcdLine1;

        while (text.length() < 16)
            text += " ";

        lcd.print(text.substring(0, 16));

        prevLine1 = lcdLine1;
    }

    // 두 번째 줄 갱신
    if (lcdLine2 != prevLine2)
    {
        lcd.setCursor(0, 1);

        String text = lcdLine2;

        while (text.length() < 16)
            text += " ";

        lcd.print(text.substring(0, 16));

        prevLine2 = lcdLine2;
    }
}
bool pollLcdCommand(){
    WiFiSSLClient client;

    Serial.println("================================");
    Serial.println("Polling LCD Command...");

    //--------------------------------------
    // SSL Connect
    //--------------------------------------

    if (!client.connect(MOBIUS_HOST, MOBIUS_PORT))
    {
        Serial.println("SSL Connect Failed");
        return false;
    }

    client.setTimeout(5000);

    //--------------------------------------
    // HTTP GET
    //--------------------------------------

    String url =
        String(MOBIUS_BASE_PATH) +
        "/deskInterface/lcdCommand/latest";

    client.println("GET " + url + " HTTP/1.1");
    client.println("Host: " + String(MOBIUS_HOST));
    client.println("Accept: application/json");

    client.println(
        "X-M2M-RI: " +
        String(DEVICE_ID) +
        "-" +
        String(millis()));

    client.println("X-M2M-Origin: S");

    client.println(
        "X-API-KEY: " +
        String(API_KEY));

    client.println(
        "X-AUTH-CUSTOM-LECTURE: " +
        String(CUSTOM_LECTURE));

    client.println(
        "X-AUTH-CUSTOM-CREATOR: " +
        String(CUSTOM_CREATOR));

    client.println("Connection: close");
    client.println();

    //--------------------------------------
    // Status Line
    //--------------------------------------

    String status = client.readStringUntil('\n');

    Serial.print("HTTP : ");
    Serial.println(status);

    if (status.indexOf("200") < 0)
    {
        client.stop();
        return false;
    }

    //--------------------------------------
    // Skip Header
    //--------------------------------------

    while (client.connected())
    {
        String line = client.readStringUntil('\n');

        if (line == "\r")
            break;
    }

    //--------------------------------------
    // Read Body
    //--------------------------------------

    String body;

    while (client.available())
    {
        body += client.readString();
    }

    client.stop();

    if (body.length() == 0)
    {
        Serial.println("Empty Body");
        return false;
    }

    Serial.println(body);

    //--------------------------------------
    // JSON Parse
    //--------------------------------------

    DynamicJsonDocument doc(2048);

    DeserializationError err =
        deserializeJson(doc, body);

    if (err)
    {
        Serial.print("JSON Error : ");
        Serial.println(err.c_str());
        return false;
    }

    JsonObject con = doc["m2m:cin"]["con"];

    if (con.isNull())
    {
        Serial.println("No con");
        return false;
    }

    //--------------------------------------
    // Command ID
    //--------------------------------------

    String commandId =
        con["commandId"] | "";

    if (commandId == "")
        return true;

    //--------------------------------------
    // Already Received
    //--------------------------------------

    if (commandId == lastCommandId)
    {
        Serial.println("Same Command");
        return true;
    }

    lastCommandId = commandId;

    //--------------------------------------
    // Session
    //--------------------------------------

    currentSessionId =
        con["sessionId"] | "";

    currentSuggestionId =
        con["suggestionId"] | "";

    //--------------------------------------
    // Screen
    //--------------------------------------

    String screen =
        con["screen"] | "";

    hasActiveSuggestion =
        (screen == "STAND_SUGGESTION");

    //--------------------------------------
    // LCD Text
    //--------------------------------------

    lcdLine1 =
        con["line1"] | "";

    lcdLine2 =
        con["line2"] | "";

    //--------------------------------------
    // Trim
    //--------------------------------------

    if (lcdLine1.length() > 16)
        lcdLine1.remove(16);

    if (lcdLine2.length() > 16)
        lcdLine2.remove(16);

    //--------------------------------------
    // Debug
    //--------------------------------------

    Serial.println("Command Updated");

    Serial.print("Session : ");
    Serial.println(currentSessionId);

    Serial.print("Suggestion : ");
    Serial.println(currentSuggestionId);

    Serial.print("Screen : ");
    Serial.println(screen);

    Serial.print("LCD1 : ");
    Serial.println(lcdLine1);

    Serial.print("LCD2 : ");
    Serial.println(lcdLine2);

    return true;
}