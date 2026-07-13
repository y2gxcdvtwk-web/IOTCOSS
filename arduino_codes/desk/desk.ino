#include <LiquidCrystal_I2C.h>
#include <Wire.h>
LiquidCrystal_I2C lcd(0x27,16,2);
/*
SCL=5
SDA=4
*/
#define Button_pin 2
int sit_height=80;
int stand_height=125;
bool sit_stand=0;//0=sit,1=stand
void setup() {
  //모터 세팅
  lcd.init();
  lcd.backlight();
  pinMode(Button_pin,INPUT);
}

int height=sit_stand?stand_height:sit_height;
void loop() {
  lcd.setCursor(0, 0);
  lcd.print("height:");
  lcd.print(height);
  lcd.print("  ");
  lcd.setCursor(0,1);
  int button=digitalRead(Button_pin);
  if(button)lcd.print("button");
  else lcd.print("       ");
  delay(100);
}
