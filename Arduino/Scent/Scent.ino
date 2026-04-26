// M5Atom で BME688 のガスセンサ・ヒーターを操作するサンプル
// 2022/1/6 @ksasao
// 
// 利用デバイス:
// デバイスは、下記などで入手してください
// BME688搭載 4種空気質センサモジュール（ガス/温度/気圧/湿度）
// https://www.switch-science.com/catalog/7383/
// 
// ライブラリの追加:
// https://github.com/BoschSensortec/Bosch-BME68x-Library
// で、Code > Download ZIP から ZIPファイルとしてダウンロードし、
// Arduino IDE の スケッチ > ライブラリをインクルード > .ZIP形式のライブラリをインストール
// からZIPファイルを登録してください。
//
// 参考:
//   https://twitter.com/ksasao/status/1479108937861709825
#include "M5Atom.h"
#include "bme68xLibrary.h"

#define NEW_GAS_MEAS (BME68X_GASM_VALID_MSK | BME68X_HEAT_STAB_MSK | BME68X_NEW_DATA_MSK)
#define MEAS_DUR 140

// Atomic proto
//#define SDA_PIN 25
//#define SCL_PIN 21
//#define BME688_I2C_ADDR 0x76

// Grove接続 / ENV Pro の場合は下記を利用してください
#define SDA_PIN 26
#define SCL_PIN 32
#define BME688_I2C_ADDR 0x77

#include <math.h>
Bme68x bme;

/**
 * @brief Initializes the sensor and hardware settings
 */
void setup(void)
{
  M5.begin(true, false, true);
  delay(50);
    
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);

  while (!Serial)
  {
    delay(10);
  }

  /* initializes the sensor based on I2C library */
  bme.begin(BME688_I2C_ADDR, Wire);

  if(bme.checkStatus())
  {
    if (bme.checkStatus() == BME68X_ERROR)
    {
      Serial.println("Sensor error:" + bme.statusString());
      return;
    }
    else if (bme.checkStatus() == BME68X_WARNING)
    {
      Serial.println("Sensor Warning:" + bme.statusString());
    }
  }
  
  /* Set the default configuration for temperature, pressure and humidity */
  bme.setTPH();

  /* ヒーターの温度(℃)の１サイクル分の温度変化。 200-400℃程度を指定。配列の長さは最大10。*/
  uint16_t tempProf[10] = { 320, 100, 100, 100, 200, 200, 200, 320, 320,320 };
  /* ヒーターの温度を保持する時間の割合。数値×MEAS_DUR(ms)保持される。保持時間は1～4032ms。指定温度に達するまで20-30ms程度が必要。 */
  uint16_t mulProf[10] = { 5, 2, 10, 30, 5, 5, 5, 5, 5, 5 };
  /* 各測定(温度,湿度,気圧,抵抗値)の繰り返し間隔(MEAS_DUR)から測定にかかる正味時間を引いたものをsharedHeatrDurに設定 */
  uint16_t sharedHeatrDur = MEAS_DUR - (bme.getMeasDur(BME68X_PARALLEL_MODE) / 1000);

  bme.setHeaterProf(tempProf, mulProf, sharedHeatrDur, 10);
  bme.setOpMode(BME68X_PARALLEL_MODE);
}

void loop(void)
{
  bme68xData data;
  uint8_t nFieldsLeft = 0;
  M5.dis.drawpix(0, 0x0000f0);
  /* data being fetched for every 140ms */
  delay(MEAS_DUR);

  if (bme.fetchData())
  {
    do
    {
      nFieldsLeft = bme.getData(data);
      if (data.status == NEW_GAS_MEAS)
      {
        if(data.gas_index == 9){
          M5.dis.drawpix(0, 0x00f000);
        }else{
          M5.dis.drawpix(0, 0xf060f0);
        }
        Serial.print(String(data.gas_index)+",");
        Serial.print(String(millis()) + ",");
        Serial.print(String(data.temperature) + ","); // 周囲の温度湿度も結構影響があります
        Serial.print(String(data.humidity) + ",");
        Serial.print(String(data.pressure) + ",");

        float current = log(data.gas_resistance); // 値の変動が大きいので対数をとるといい感じです
        Serial.println(String(current,3));
        delay(20);
        M5.dis.drawpix(0, 0x0000f0);
      }
    } while (nFieldsLeft);
  }
}