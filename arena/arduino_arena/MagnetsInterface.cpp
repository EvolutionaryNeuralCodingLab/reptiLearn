/* Interface for BTS7960 motor driver (magnets control)
 * ----------------------------------------------------
 * @author Ofek Sapir
 */

#include "MagnetsInterface.h"

MagnetsInterface::MagnetsInterface(JsonObject conf)
  : Interface("magnets", strdup(conf["name"].as<const char*>())),
    rpwm_pin(-1),
    lpwm_pin(-1),
    pwm_value(255),
    state(magnets_stop) {
  if (!conf.containsKey("rpwm_pin")) {
    send_error("Missing 'rpwm_pin' key in config");
    return;
  }
  if (!conf.containsKey("lpwm_pin")) {
    send_error("Missing 'lpwm_pin' key in config");
    return;
  }
  if (!conf["rpwm_pin"].is<int>() || !conf["lpwm_pin"].is<int>()) {
    send_error("rpwm_pin and lpwm_pin must be integers");
    return;
  }

  rpwm_pin = conf["rpwm_pin"].as<int>();
  lpwm_pin = conf["lpwm_pin"].as<int>();

  if (conf.containsKey("pwm_value") && conf["pwm_value"].is<int>()) {
    pwm_value = constrain(conf["pwm_value"].as<int>(), 0, 255);
  }

  pinMode(rpwm_pin, OUTPUT);
  pinMode(lpwm_pin, OUTPUT);
  analogWrite(rpwm_pin, 0);
  analogWrite(lpwm_pin, 0);
}

void MagnetsInterface::set_state(MagnetsState s) {
  state = s;
  if (rpwm_pin < 0 || lpwm_pin < 0) return;

  switch (state) {
    case magnets_forward:
      analogWrite(rpwm_pin, pwm_value);
      analogWrite(lpwm_pin, 0);
      break;
    case magnets_reverse:
      analogWrite(rpwm_pin, 0);
      analogWrite(lpwm_pin, pwm_value);
      break;
    case magnets_stop:
    default:
      analogWrite(rpwm_pin, 0);
      analogWrite(lpwm_pin, 0);
      break;
  }
}

void MagnetsInterface::get_value(JsonDocument* container) {
  const char* s = "stop";
  if (state == magnets_forward) s = "forward";
  else if (state == magnets_reverse) s = "reverse";
  container->set(s);
}

void MagnetsInterface::run(JsonArray cmd) {
  if (rpwm_pin < 0 || lpwm_pin < 0) {
    send_error("Interface not properly initialized");
    return;
  }

  const char* c = cmd[0].as<const char*>();
  if (strcmp(c, "forward") == 0) {
    set_state(magnets_forward);
    send_info("Forward");
  } else if (strcmp(c, "reverse") == 0) {
    set_state(magnets_reverse);
    send_info("Reverse");
  } else if (strcmp(c, "stop") == 0) {
    set_state(magnets_stop);
    send_info("Stop");
  } else {
    send_error("Unknown command. Use forward, reverse, or stop.");
  }
}

void MagnetsInterface::loop() {
  // No ongoing logic needed; PWM is held by analogWrite
}
