#include "show.h"
#include "sys.h"
#include "delay.h"
#include "oled.h"
void page_one(void)
{
	OLED_Clear();
	//电机角度
	OLED_ShowCHinese(32,0,0);OLED_ShowCHinese(32+16,0,1);OLED_ShowCHinese(32+32,0,12);OLED_ShowCHinese(32+48,0,13);
	//电机使能
  OLED_ShowCHinese(0,2,0);OLED_ShowCHinese(0+16,2,1);OLED_ShowCHinese(0+32,2,4);OLED_ShowCHinese(0+48,2,5);
	//电机告警
	OLED_ShowCHinese(0,4,0);OLED_ShowCHinese(0+16,4,1);OLED_ShowCHinese(0+32,4,6);OLED_ShowCHinese(0+48,4,7);
	//电机速度
	OLED_ShowCHinese(0,6,0);OLED_ShowCHinese(0+16,6,1);OLED_ShowCHinese(0+32,6,14);OLED_ShowCHinese(0+48,6,15);
	
//  OLED_ShowString(64,0,":000.0*C",16);
	OLED_ShowString(64,2,":       ",16);
	OLED_ShowString(64,4,":       ",16);
	OLED_ShowString(64,6,":00rad/s",16);
}



