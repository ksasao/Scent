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

// CRC-8 lookup table (AUTOSAR polynomial 0x31)
const PROGMEM uint8_t CRC8_TABLE[256] = {
  0x00, 0x31, 0x62, 0x53, 0xC4, 0xF5, 0xA6, 0x97, 0xB9, 0x88, 0xDB, 0xEA, 0x7D, 0x4C, 0x1F, 0x2E,
  0x43, 0x72, 0x21, 0x10, 0x87, 0xB6, 0xE5, 0xD4, 0xFA, 0xCB, 0x98, 0xA9, 0x3E, 0x0F, 0x5C, 0x6D,
  0x86, 0xB7, 0xE4, 0xD5, 0x42, 0x73, 0x20, 0x11, 0x3F, 0x0E, 0x5D, 0x6C, 0xFB, 0xCA, 0x99, 0xA8,
  0xC5, 0xF4, 0xA7, 0x96, 0x01, 0x30, 0x63, 0x52, 0x7C, 0x4D, 0x1E, 0x2F, 0xB8, 0x89, 0xDA, 0xEB,
  0x0C, 0x3D, 0x6E, 0x5F, 0xC8, 0xF9, 0xAA, 0x9B, 0xB5, 0x84, 0xD7, 0xE6, 0x71, 0x40, 0x13, 0x22,
  0x4F, 0x7E, 0x2D, 0x1C, 0x8B, 0xBA, 0xE9, 0xD8, 0xF6, 0xC7, 0x94, 0xA5, 0x32, 0x03, 0x50, 0x61,
  0x8A, 0xBB, 0xE8, 0xD9, 0x4E, 0x7F, 0x2C, 0x1D, 0x33, 0x02, 0x51, 0x60, 0xF7, 0xC6, 0x95, 0xA4,
  0xC9, 0xF8, 0xAB, 0x9A, 0x0D, 0x3C, 0x6F, 0x5E, 0x70, 0x41, 0x12, 0x23, 0xB4, 0x85, 0xD6, 0xE7,
  0x18, 0x29, 0x7A, 0x4B, 0xDC, 0xED, 0xBE, 0x8F, 0xA1, 0x90, 0xC3, 0xF2, 0x65, 0x54, 0x07, 0x36,
  0x5B, 0x6A, 0x39, 0x08, 0x9F, 0xAE, 0xFD, 0xCC, 0xE2, 0xD3, 0x80, 0xB1, 0x26, 0x17, 0x44, 0x75,
  0x9E, 0xAF, 0xFC, 0xCD, 0x5A, 0x6B, 0x38, 0x09, 0x27, 0x16, 0x45, 0x74, 0xE3, 0xD2, 0x81, 0xB0,
  0xDD, 0xEC, 0xBF, 0x8E, 0x19, 0x28, 0x7B, 0x4A, 0x64, 0x55, 0x06, 0x37, 0xA0, 0x91, 0xC2, 0xF3,
  0x14, 0x25, 0x76, 0x47, 0xD0, 0xE1, 0xB2, 0x83, 0xAD, 0x9C, 0xCF, 0xFE, 0x69, 0x58, 0x0B, 0x3A,
  0x57, 0x66, 0x35, 0x04, 0x93, 0xA2, 0xF1, 0xC0, 0xEE, 0xDF, 0x8C, 0xBD, 0x2A, 0x1B, 0x48, 0x79,
  0xB2, 0x83, 0xD0, 0xE1, 0x76, 0x47, 0x14, 0x25, 0x0B, 0x3A, 0x69, 0x58, 0xCF, 0xFE, 0xAD, 0x9C,
  0xF1, 0xC0, 0x93, 0xA2, 0x35, 0x04, 0x57, 0x66, 0x48, 0x79, 0x2A, 0x1B, 0x8C, 0xBD, 0xEE, 0xDF
};

uint8_t crc8(const String& data) {
  uint8_t crc = 0;
  for (int i = 0; i < data.length(); i++) {
    uint8_t byte = data.charAt(i);
    crc = pgm_read_byte(&CRC8_TABLE[crc ^ byte]);
  }
  return crc;
}

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
        
        // Build data string for CRC calculation
        String dataStr = String(data.gas_index) + "," +
                        String(data.temperature) + "," +
                        String(data.humidity) + "," +
                        String(data.pressure) + "," +
                        String(current, 3);
        
        // Calculate CRC-8 (AUTOSAR polynomial 0x31)
        uint8_t crc = crc8(dataStr);
        
        Serial.print(dataStr + ",");
        Serial.print(String(crc, HEX));
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