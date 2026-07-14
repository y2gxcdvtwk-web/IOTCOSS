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
void change(int event,int *height){
  switch(event){
    case 0://시작
    if(height==stand_height){
      height=sit_height;
      change(2,NULL);
    }
    
    break;
    case 1://미세조정 up
    case 2://미세조정 down
    
    break;
    case 3://일어나거나 앉거나
    sit_stand=sit_stand?0:1;
    break;
  }
  height=sit_stand?stand_height:sit_height;
}
void setup() {
  //+모터 세팅
  lcd.init();
  lcd.backlight();
  pinMode(Button_pin,INPUT);
}
int *height=sit_stand?stand_height:sit_height;
void loop() {
  int button;
  int start_time=0;
  change(0,NULL);
  lcd.setCursor(0, 0);
  lcd.print("height:");
  lcd.print(*height);
  lcd.print("  ");
  if(event){
    start_time=0;//get time
    while(term<10sec){  
      button=digitalRead(Button_pin);
      lcd.setCursor(0,1); 
      if(button){
        change(event,height);
        lcd.print("button");
      }
      else lcd.print("       ");
      delay(50);
    }
  }
  lcd.setCursor(0,1);
  int button=digitalRead(Button_pin);
  if(button)lcd.print("button");
  else lcd.print("       ");
  delay(100);
}
