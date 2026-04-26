// Sample sketch for controlling BME688 gas sensor and heater with M5Atom
// 2022/1/6 @ksasao
//
// Required device:
// Purchase the following or equivalent device:
// ENV Pro Unit with Temperature, Humidity, Pressure and Gas Sensor (BME688)
// https://shop.m5stack.com/products/env-pro-unit-with-temperature-humidity-pressure-and-gas-sensor-bme688
//
// Adding the library:
// Download as ZIP from:
// https://github.com/BoschSensortec/Bosch-BME68x-Library
// (Code > Download ZIP), then register it via
// Arduino IDE: Sketch > Include Library > Add .ZIP Library
//
// Reference:
//   https://twitter.com/ksasao/status/1479108937861709825
#include "M5Atom.h"
#include "bme68xLibrary.h"

#define NEW_GAS_MEAS (BME68X_GASM_VALID_MSK | BME68X_HEAT_STAB_MSK | BME68X_NEW_DATA_MSK)
#define MEAS_DUR 140
#define NO_DATA_RESET_MS 10000UL
#define SENSOR_RECOVER_INTERVAL_MS 1000UL

// Use the following for Grove connection / ENV Pro
#define SDA_PIN 26
#define SCL_PIN 32
#define BME688_I2C_ADDR 0x77

#include <math.h>
Bme68x bme;
uint32_t last_valid_ms = 0;
uint32_t last_recover_attempt_ms = 0;

bool init_bme688()
{
  /* initializes the sensor based on I2C library */
  bme.begin(BME688_I2C_ADDR, Wire);

  if (bme.checkStatus())
  {
    if (bme.checkStatus() == BME68X_ERROR)
    {
      Serial.println("Sensor error:" + bme.statusString());
      return false;
    }
    else if (bme.checkStatus() == BME68X_WARNING)
    {
      Serial.println("Sensor Warning:" + bme.statusString());
    }
  }

  /* Set the default configuration for temperature, pressure and humidity */
  bme.setTPH();

  /* Heater temperature profile (°C) for one cycle. Specify around 200-400°C. Max array length is 10. */
  uint16_t tempProf[10] = { 320, 100, 100, 100, 200, 200, 200, 320, 320,320 };
  /* Duration multiplier for each heater step. Held for value × MEAS_DUR (ms). Valid range: 1–4032 ms. Allow ~20-30 ms to reach target temperature. */
  uint16_t mulProf[10] = { 5, 2, 10, 30, 5, 5, 5, 5, 5, 5 };
  /* Set sharedHeatrDur to MEAS_DUR minus the net measurement duration */
  uint16_t sharedHeatrDur = MEAS_DUR - (bme.getMeasDur(BME68X_PARALLEL_MODE) / 1000);

  bme.setHeaterProf(tempProf, mulProf, sharedHeatrDur, 10);
  bme.setOpMode(BME68X_PARALLEL_MODE);
  return true;
}

/**
 * @brief Initializes the sensor and hardware settings
 */
void setup(void)
{
  M5.begin(true, false, true);
  delay(50);
    
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);

  M5.dis.drawpix(0, 0xf00000);
  delay(1000);

  while (!Serial)
  {
    delay(10);
  }

  init_bme688();
  last_valid_ms = millis();
}

void loop(void)
{
  M5.update();
  /* Handle serial commands from host */
  if (Serial.available() > 0)
  {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "id")
    {
      uint32_t uid = bme.getUniqueId();
      char buf[9];
      snprintf(buf, sizeof(buf), "%08lX", (unsigned long)uid);
      Serial.println("ID," + String(buf));
    }
  }

  bme68xData data;
  uint8_t nFieldsLeft = 0;
  bool has_valid_measurement = false;
  M5.dis.drawpix(0, 0x0000f0);
  /* data being fetched for every 140ms */
  delay(MEAS_DUR);

  if (bme.fetchData())
  {
    do
    {
      nFieldsLeft = bme.getData(data);
      if ((data.status & NEW_GAS_MEAS) == NEW_GAS_MEAS)
      {
        has_valid_measurement = true;
        if(data.gas_index == 9){
          M5.dis.drawpix(0, 0x00f000);
        }else{
          M5.dis.drawpix(0, 0xf060f0);
        }
        float current = log(data.gas_resistance); // Log scale works well due to large variation in gas resistance
        
        // Build data string for checksum calculation
        String dataStr = String(data.gas_index) + "," +
                        String(data.temperature) + "," +
                        String(data.humidity) + "," +
                        String(data.pressure) + "," +
                        String(current, 3);
        
        // Calculate simple checksum (XOR of all characters)
        uint8_t checksum = 0;
        for (int i = 0; i < dataStr.length(); i++) {
          checksum ^= dataStr.charAt(i);
        }
        
        Serial.print(dataStr + ",");
        Serial.print(String(checksum, HEX));
        Serial.println();
        delay(20);
        M5.dis.drawpix(0, 0x0000f0);
      }
    } while (nFieldsLeft);
  }
  else
  {
    /* Recover from hot-plug/I2C errors without waiting for full board reset */
    if ((bme.checkStatus() == BME68X_ERROR) && ((uint32_t)(millis() - last_recover_attempt_ms) >= SENSOR_RECOVER_INTERVAL_MS))
    {
      last_recover_attempt_ms = millis();
      Serial.println("WARN,BME688 communication error. Reinitializing sensor...");
      if (init_bme688())
      {
        last_valid_ms = millis();
        Serial.println("INFO,BME688 reinitialized");
      }
    }
  }

  if (has_valid_measurement)
  {
    last_valid_ms = millis();
  }
  else if ((uint32_t)(millis() - last_valid_ms) > NO_DATA_RESET_MS)
  {
    Serial.println("WARN,No valid BME688 data for 10s. Resetting...");
    delay(100);
    ESP.restart();
  }
}