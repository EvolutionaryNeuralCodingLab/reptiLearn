#ifndef LIS3MDLInterface_h
#define LIS3MDLInterface_h

#include "Interface.h"
#include <Wire.h>
#include <ArduinoJson.h>

//#include <string>

// LIS3MDL I2C addresses
#define LIS3MDL_ADDRESS_1  0x1E  // SA0/SA1 pin high
#define LIS3MDL_ADDRESS_2  0x1C  // SA0/SA1 pin low

class LIS3MDLInterface : public Interface {
 public:
  LIS3MDLInterface(JsonVariant conf);

  void get_value(JsonDocument* container) override;
  void run(JsonArray cmd) override;
  void loop() override;
  bool checkSensor();
  void initSensor();
  void readSensor();
  void writeRegister(uint8_t reg, uint8_t value);
 private:
  String temp;
  uint8_t address;
  int x, y, z;


};

#endif
