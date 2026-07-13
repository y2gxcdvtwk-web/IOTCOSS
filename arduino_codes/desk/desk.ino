#include <LiquidCrystal_I2C.h>
#include <Wire.h>
LiquidCrystal_I2C lcd(0x27,16,2);
/*
SCL=5
SDA=4
*/
int sit_height=80;
int stand_height=125;
void setup() {
  //모터 세팅
  lcd.init();
  lcd.backlight();
}

void loop() {
  lcd.setCursor(0, 0);
  lcd.print("hello");
}
