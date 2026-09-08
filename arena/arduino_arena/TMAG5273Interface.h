#ifndef TMAG5273Interface_h
#define TMAG5273Interface_h

#include "Interface.h"
#include <ArduinoJson.h>
#include <SparkFun_TMAG5273_Arduino_Library.h>

class TMAG5273Interface : public Interface {
 public:
  TMAG5273Interface(JsonVariant conf);

  void get_value(JsonDocument* container) override;
  void run(JsonArray cmd) override;
  void loop() override;

 private:
  TMAG5273* sensor;
  uint8_t i2c_address;
  unsigned long auto_poll_ms;
  unsigned long last_poll_time;
  unsigned long min_read_interval_ms;
  unsigned long last_read_time;

  bool filter_initialized;

  float filt_x_uT;
  float filt_y_uT;
  float filt_z_uT;
  float filt_b_uT;

  float cached_x_uT;
  float cached_y_uT;
  float cached_z_uT;
  float cached_b_uT;
  void readMagneticField(float* x_uT, float* y_uT, float* z_uT, float* b_uT);
};

#endif
