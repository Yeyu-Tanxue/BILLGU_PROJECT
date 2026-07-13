#include "myiic.h"
#include "delay.h"
//////////////////////////////////////////////////////////////////////////////////	 
//本程序只供学习使用，未经作者许可，不得用于其它任何用途
//Mini STM32开发板
//IIC 驱动函数	   
//正点原子@ALIENTEK
//技术论坛:www.openedv.com
//修改日期:2010/6/10 
//版本：V1.0
//版权所有，盗版必究。
//Copyright(C) 正点原子 2009-2019
//All rights reserved
////////////////////////////////////////////////////////////////////////////////// 	  

//初始化IIC
void AS5600_IIC_Init(void)
{					     
	GPIO_InitTypeDef GPIO_InitStructure;
	//RCC->APB2ENR|=1<<4;//先使能外设IO PORTC时钟 
	RCC_APB2PeriphClockCmd(	RCC_APB2Periph_GPIOB, ENABLE );	
	   
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_10|GPIO_Pin_11;
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP ;   //推挽输出
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
	GPIO_Init(GPIOB, &GPIO_InitStructure);
 
	AS5600_IIC_SCL=1;
	AS5600_IIC_SDA=1;

}
//产生IIC起始信号
void AS5600_IIC_Start(void)
{
	AS5600_SDA_OUT();     //sda线输出
	AS5600_IIC_SDA=1;	  	  
	AS5600_IIC_SCL=1;
	delay_us(4);
 	AS5600_IIC_SDA=0;//START:when CLK is high,DATA change form high to low 
	delay_us(4);
	AS5600_IIC_SCL=0;//钳住I2C总线，准备发送或接收数据 
}	  
//产生IIC停止信号
void AS5600_IIC_Stop(void)
{
	AS5600_SDA_OUT();//sda线输出
	AS5600_IIC_SCL=0;
	AS5600_IIC_SDA=0;//STOP:when CLK is high DATA change form low to high
 	delay_us(4);
	AS5600_IIC_SCL=1; 
	AS5600_IIC_SDA=1;//发送I2C总线结束信号
	delay_us(4);							   	
}
//等待应答信号到来
//返回值：1，接收应答失败
//        0，接收应答成功
u8 AS5600_IIC_Wait_Ack(void)
{
	u8 ucErrTime=0;
	AS5600_SDA_IN();      //SDA设置为输入  
	AS5600_IIC_SDA=1;delay_us(1);	   
	AS5600_IIC_SCL=1;delay_us(1);	 
	while(AS5600_READ_SDA)
	{
		ucErrTime++;
		if(ucErrTime>250)
		{
			AS5600_IIC_Stop();
			return 1;
		}
	}
	AS5600_IIC_SCL=0;//时钟输出0 	   
	return 0;  
} 
//产生ACK应答
void AS5600_IIC_Ack(void)
{
	AS5600_IIC_SCL=0;
	AS5600_SDA_OUT();
	AS5600_IIC_SDA=0;
	delay_us(2);
	AS5600_IIC_SCL=1;
	delay_us(2);
	AS5600_IIC_SCL=0;
}
//不产生ACK应答		    
void AS5600_IIC_NAck(void)
{
	AS5600_IIC_SCL=0;
	AS5600_SDA_OUT();
	AS5600_IIC_SDA=1;
	delay_us(2);
	AS5600_IIC_SCL=1;
	delay_us(2);
	AS5600_IIC_SCL=0;
}					 				     
//IIC发送一个字节
//返回从机有无应答
//1，有应答
//0，无应答			  
void AS5600_IIC_Send_Byte(u8 txd)
{                        
    u8 t;   
	AS5600_SDA_OUT(); 	    
    AS5600_IIC_SCL=0;//拉低时钟开始数据传输
    for(t=0;t<8;t++)
    {              
        AS5600_IIC_SDA=(txd&0x80)>>7;
        txd<<=1; 	  
		delay_us(2);   //对TEA5767这三个延时都是必须的
		AS5600_IIC_SCL=1;
		delay_us(2); 
		AS5600_IIC_SCL=0;	
		delay_us(2);
    }	 
} 	    
//读1个字节，ack=1时，发送ACK，ack=0，发送nACK   
u8 AS5600_IIC_Read_Byte(unsigned char ack)
{
	unsigned char i,receive=0;
	AS5600_SDA_IN();//SDA设置为输入
    for(i=0;i<8;i++ )
	{
        AS5600_IIC_SCL=0; 
        delay_us(2);
		AS5600_IIC_SCL=1;
        receive<<=1;
        if(AS5600_READ_SDA)receive++;   
		delay_us(1); 
    }					 
    if (!ack)
        AS5600_IIC_NAck();//发送nACK
    else
        AS5600_IIC_Ack(); //发送ACK   
    return receive;
}


//函数：u8 AS5600_ReadOneByte(u16 ReadAddr)
//功能：从AS5600模块读取一个字节的数据
//参数：ReadAddr    要读取的地址
//返回：读取到的数据
u8 AS5600_ReadOneByte(u16 ReadAddr)
{                  
    u8 temp=0;                                                                                   
  AS5600_IIC_Start();  
    AS5600_IIC_Send_Byte((0x36<<1)|0x00);       //
    AS5600_IIC_Wait_Ack(); 
  AS5600_IIC_Send_Byte(ReadAddr);   //
    AS5600_IIC_Wait_Ack();        
    AS5600_IIC_Start();              
    AS5600_IIC_Send_Byte((0x36<<1)|0x01);           //           
    AS5600_IIC_Wait_Ack();     
  temp=AS5600_IIC_Read_Byte(0);           
  AS5600_IIC_Stop();//       
    return temp;
}


//函数功能：向AS5600写入一个字节
void AS5600_WriteOneByte(u16 WriteAddr,u8 WriteData)
{				  	  	    																 
  //开始发送
  AS5600_IIC_Start();  
	//发送地址位0x36，写操作
	AS5600_IIC_Send_Byte((0X36<<1)|0x00);	  
	AS5600_IIC_Wait_Ack(); //等待响应
  //发送写入地址
  AS5600_IIC_Send_Byte(WriteAddr);   
	AS5600_IIC_Wait_Ack();	    //等待响应
  //发送写入数据
	AS5600_IIC_Start();  	 	   
	AS5600_IIC_Send_Byte(WriteData);        
	AS5600_IIC_Wait_Ack();	 	   
  //结束发送
  AS5600_IIC_Stop();
	delay_ms(10);
}

//读2个字节数据，获取原始角度
u16 AS5600_ReadTwoByte(u16 ReadAddr_hi,u16 ReadAddr_lo)
{
	u16 TwoByte_Data = 0;
	u8 hi_Data = 0,lo_Data = 0;
	//Read the first byte (higher address)
	hi_Data = AS5600_ReadOneByte(ReadAddr_hi);
	//Read the second byte (lower address)
	lo_Data = AS5600_ReadOneByte(ReadAddr_lo);
	//Combine the two bytes into a single 16-bit value
	TwoByte_Data = (hi_Data<<8)|lo_Data;
	//Return the 16-bit value
	return TwoByte_Data;
}























