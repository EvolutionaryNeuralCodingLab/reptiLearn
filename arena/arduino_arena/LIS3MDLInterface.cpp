#include "LIS3MDLInterface.h"
#include "send.h"
#include <Wire.h>
//#include <string>
#define WHO_AM_I    0x0F
#define OUT_X_L     0x28
#define OUT_X_H     0x29
#define OUT_Y_L     0x2A
#define OUT_Y_H     0x2B
#define OUT_Z_L     0x2C
#define OUT_Z_H     0x2D

LIS3MDLInterface::LIS3MDLInterface(JsonVariant conf)
  : Interface("lis3mdl", strdup(conf["name"])), x(0), y(0), z(0) {

  if (!conf.containsKey("address")) {
    send_error("Missing 'address' key in config");
    return;
  }
  temp = conf["address"].as<String>();
  if (temp != "high" && temp != "low"){
    send_error("'address' value should be 'high' or 'low'");
    return;
  }
  if (temp == "high") {
    address = LIS3MDL_ADDRESS_1; // Use 0x1E
  }
  if (temp == "low") {
    address = LIS3MDL_ADDRESS_2; // Use 0x1C
  }
  if (!checkSensor()) {
    send_error("Sensor not detected at specified address");
    return;
  }

  initSensor();
  send_info("Sensor initialized");
}

bool LIS3MDLInterface::checkSensor() {
    send_info("Attempting to detect sensor at address: 0x");
    send_info(address);

    Wire.beginTransmission(address);
    Wire.write(WHO_AM_I);
    Wire.endTransmission();
    Wire.requestFrom(address, (uint8_t)1); // Use correct type

    if (Wire.available()) {
        byte who_am_i = Wire.read();
        send_info("WHO_AM_I register value: ");
        send_error(who_am_i);
        return (who_am_i == 0x3D);
    } else {
        send_error("Error: WHO_AM_I register not available");
        return false;
    }
}

void LIS3MDLInterface::initSensor() {
    send_info("Initializing sensor with configuration...");
    writeRegister(0x20, 0x70);  // CTRL_REG1
    writeRegister(0x21, 0x00);  // CTRL_REG2
    writeRegister(0x22, 0x00);  // CTRL_REG3
    writeRegister(0x23, 0x0C);  // CTRL_REG4
    send_info("Sensor initialized.");
}

void LIS3MDLInterface::readSensor() {
  Wire.beginTransmission(address);
  Wire.write(0x28);  // OUT_X_L register
  Wire.endTransmission();
  Wire.requestFrom(address, (uint8_t)6);

  if (Wire.available() == 6) {
    x = Wire.read() | (Wire.read() << 8);
    y = Wire.read() | (Wire.read() << 8);
    z = Wire.read() | (Wire.read() << 8);
  } else {
    send_error("Error: Data not available");
  }
}

void LIS3MDLInterface::writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

void LIS3MDLInterface::get_value(JsonDocument* container) {
  JsonArray readings = container->to<JsonArray>();

  readSensor();

  readings.add(x);
  readings.add(y);
  readings.add(z);
}

void LIS3MDLInterface::run(JsonArray cmd) {
  if (cmd[0] == "get") {
    serializeValue();
  } else {
    send_error("Unknown command");
  }
}

void LIS3MDLInterface::loop() {
  // This function could be used to perform periodic tasks if necessary
}
