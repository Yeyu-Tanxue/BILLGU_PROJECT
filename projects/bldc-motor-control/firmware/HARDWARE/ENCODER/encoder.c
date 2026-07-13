#include "encoder.h"
#include "main.h"

uchar WheelNow,WheelOld,RightCount,LeftCount;
uchar WheelRight()
{
		LeftCount=0;
		RightCount++;
		if (RightCount>=cycle)
			{
			RightCount=0;
			return(E_RIGHT);
		  }  
	else return(NULL);
}

uchar WheelLeft()
{
    RightCount=0;
    LeftCount++;
    if (LeftCount>=cycle)
			{
        LeftCount=0;
        return(E_LEFT);
      } 
			else return(NULL);
}
uchar EncoderProcess()
{
		uchar keytmp;
		GPIO_SetBits(GPIOB,GPIO_Pin_12);
		GPIO_SetBits(GPIOB,GPIO_Pin_13);
		WheelNow=WheelNow<<1;
		if (GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_12) == 1) WheelNow=WheelNow+1;  
		WheelNow=WheelNow<<1;
		if (GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_13) == 1) WheelNow=WheelNow+1;  
		WheelNow=WheelNow & 0x03;  
		if (WheelNow==0x00) return(NULL); 
		keytmp=WheelNow;
		keytmp ^=WheelOld; 
		if (keytmp==0) return(NULL); 
												 
		if (WheelOld==0x01 && WheelNow==0x02){ 
		WheelOld=WheelNow;
		return(WheelLeft()); 
		}
		else if (WheelOld==0x02 && WheelNow==0x01){ 
		WheelOld=WheelNow;
		return(WheelRight()); 
		}
		WheelOld=WheelNow; 
		return(NULL); 
}

void inc()
{
  motor_speed+=1;
	if(motor_speed>=5)motor_speed=5;
} 

void dec()
{	
  if(motor_speed>=1)motor_speed-=1;
	else motor_speed=0;
}
