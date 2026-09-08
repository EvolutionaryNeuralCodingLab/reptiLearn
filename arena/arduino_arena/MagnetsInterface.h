/* Interface for BTS7960 motor driver (magnets control)
 * ----------------------------------------------------
 * @author Ofek Sapir
 */

#ifndef MagnetsInterface_h
#define MagnetsInterface_h

#include "Arduino.h"
#include <ArduinoJson.h>
#include "Interface.h"

enum MagnetsState {
  magnets_stop,
  magnets_forward,
  magnets_reverse,
};

class MagnetsInterface : public Interface {
 public:
  MagnetsInterface(JsonObject conf);

  void get_value(JsonDocument* container);
  void run(JsonArray cmd);
  void loop();

 private:
  int rpwm_pin;
  int lpwm_pin;
  int pwm_value;
  MagnetsState state;
  void set_state(MagnetsState s);
};

#endif
