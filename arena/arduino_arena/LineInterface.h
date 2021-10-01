#ifndef LineInterface_h
#define LineInterface_h

#include "Arduino.h"
#include <ArduinoJson.h>
#include "Interface.h"
#include "ToggleInterface.h"

class LineInterface: public ToggleInterface {
 public:
  LineInterface(JsonVariant conf);
  void value_changed();
  void loop();
  
 private:
  int pin;
};

#endif
