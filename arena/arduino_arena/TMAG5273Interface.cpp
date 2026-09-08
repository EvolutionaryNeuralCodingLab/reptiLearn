#include "TMAG5273Interface.h"
#include "send.h"
#include <math.h>

TMAG5273Interface::TMAG5273Interface(JsonVariant conf)
  : Interface("tmag5273", strdup(conf["name"]))
  , sensor(nullptr)
  , i2c_address(TMAG5273_I2C_ADDRESS_INITIAL)
  , auto_poll_ms(0)
  , last_poll_time(0) 
  , min_read_interval_ms(100)
  , last_read_time(0)
  , filter_initialized(false)
  , filt_x_uT(0)
  , filt_y_uT(0)
  , filt_z_uT(0)
  , filt_b_uT(0)
  , cached_x_uT(0)
  , cached_y_uT(0)
  , cached_z_uT(0)
  , cached_b_uT(0) {

  if (conf.containsKey("i2c_address")) {
    if (!conf["i2c_address"].is<int>()) {
      send_error("i2c_address value should be an integer (e.g. 34 for 0x22)");
      return;
    }
    i2c_address = (uint8_t)conf["i2c_address"].as<int>();
  }

  if (conf.containsKey("auto_poll_ms")) {
    if (!conf["auto_poll_ms"].is<unsigned long>() && !conf["auto_poll_ms"].is<int>()) {
      send_error("auto_poll_ms value should be a positive integer");
      return;
    }
    auto_poll_ms = conf["auto_poll_ms"].as<unsigned long>();
  }

  sensor = new TMAG5273();
  if (sensor->begin(i2c_address, Wire) != 1) {
    send_error("TMAG5273 not detected. Check wiring and i2c_address.");
    delete sensor;
    sensor = nullptr;
    return;
  }

  sensor->setXYAxisRange(TMAG5273_RANGE_40MT);
  sensor->setZAxisRange(TMAG5273_RANGE_40MT);
  sensor->setConvAvg(TMAG5273_X32_CONVERSION);
  sensor->setOperatingMode(TMAG5273_CONTINUOUS_MEASURE_MODE);

  char msg[48];
  sprintf(msg, "TMAG5273 initialized at I2C 0x%02X (uT)", i2c_address);
  send_info(msg);
}

void TMAG5273Interface::readMagneticField(float* x_uT, float* y_uT, float* z_uT, float* b_uT) {
  const int N = 20;
  const int delay_ms = 5;

  float sum_x = 0;
  float sum_y = 0;
  float sum_z = 0;

  for (int i = 0; i < N; i++) {
    float x = sensor->getXData() * 1000.0f;
    float y = sensor->getYData() * 1000.0f;
    float z = sensor->getZData() * 1000.0f;

    sum_x += x;
    sum_y += y;
    sum_z += z;

    delay(delay_ms);
  }

  float avg_x = sum_x / N;
  float avg_y = sum_y / N;
  float avg_z = sum_z / N;

  // Optional extra smoothing between calls
  const float alpha = 0.3f;

  if (!filter_initialized) {
    filt_x_uT = avg_x;
    filt_y_uT = avg_y;
    filt_z_uT = avg_z;
    filter_initialized = true;
  } else {
    filt_x_uT = alpha * avg_x + (1.0f - alpha) * filt_x_uT;
    filt_y_uT = alpha * avg_y + (1.0f - alpha) * filt_y_uT;
    filt_z_uT = alpha * avg_z + (1.0f - alpha) * filt_z_uT;
  }

  filt_b_uT = sqrt(
    filt_x_uT * filt_x_uT +
    filt_y_uT * filt_y_uT +
    filt_z_uT * filt_z_uT
  );

  *x_uT = filt_x_uT;
  *y_uT = filt_y_uT;
  *z_uT = filt_z_uT;
  *b_uT = filt_b_uT;
}

void TMAG5273Interface::get_value(JsonDocument* container) {
  if (sensor == nullptr) {
    send_error("Sensor not initialized");
    return;
  }

  float x_uT, y_uT, z_uT, b_uT;
  readMagneticField(&x_uT, &y_uT, &z_uT, &b_uT);

  JsonArray readings = container->to<JsonArray>();
  readings.add(x_uT);
  readings.add(y_uT);
  readings.add(z_uT);
  readings.add(b_uT);
}

void TMAG5273Interface::run(JsonArray cmd) {
  if (cmd[0] == "get") {
    serializeValue();
  } else if (cmd[0] == "reset_filter") {
    filter_initialized = false;
    send_info("TMAG5273 filter reset");
  } else {
    send_error("Unknown command");
  }
}

void TMAG5273Interface::loop() {
  if (sensor == nullptr || auto_poll_ms == 0) {
    return;
  }

  unsigned long now = millis();
  if (now - last_poll_time >= auto_poll_ms) {
    last_poll_time = now;
    serializeValue();
  }
}
