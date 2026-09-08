
#include "Arduino.h"
#include "DCDoor.h"
#include "Interface.h"

DCDoor::DCDoor(JsonObject conf) : Interface("dcdoor", strdup(conf["name"].as<const char*>()))
{
    if (!conf.containsKey("open_pin")) {
        send_error("Missing 'open_pin' key in config");
        return;
    }
    if (!conf.containsKey("close_pin")) {
        send_error("Missing 'close_pin' key in config");
        return;
    }
    if (!conf["open_pin"].is<int>() || !conf["close_pin"].is<int>()) {
        send_error("pins: Each element should be an integer");
        return;
    }

    opening_pin = conf["open_pin"].as<int>();
    closing_pin = conf["close_pin"].as<int>();

    // Optional enable pin for L298N (ENA)
    if (conf.containsKey("ena_pin")) {
        if (!conf["ena_pin"].is<int>()) {
            send_error("ena_pin should be an integer");
            return;
        }
        enable_pin = conf["ena_pin"].as<int>();
        pinMode(enable_pin, OUTPUT);
        digitalWrite(enable_pin, LOW);
    } else {
        enable_pin = -1;
    }

    pinMode(opening_pin, OUTPUT);
    pinMode(closing_pin, OUTPUT);
    digitalWrite(closing_pin, LOW);
    digitalWrite(opening_pin, LOW);
    state = closed;

}


void DCDoor::loop() {
    // TODO encoding of door position
    // TODO correction of position accordingly
    if (state == closing) {
        if (millis() - action_start_time > CLOSE_TIME) {
            digitalWrite(closing_pin, LOW);
            digitalWrite(opening_pin, LOW);
            if (enable_pin != -1) {
                digitalWrite(enable_pin, LOW);
            }
            state = closed;
        }
    }
    if (state == opening) {
        if (millis() - action_start_time > OPEN_TIME) {
            digitalWrite(opening_pin, LOW);
            digitalWrite(closing_pin, LOW);
            if (enable_pin != -1) {
                digitalWrite(enable_pin, LOW);
            }
            state = opened;
        }
    }
}

void DCDoor::close() {
    state = closing;
    action_start_time = millis();
    if (enable_pin != -1) {
        digitalWrite(enable_pin, HIGH);
    }
    digitalWrite(opening_pin, LOW);
    digitalWrite(closing_pin, HIGH);
}

void DCDoor::open() {
    state = opening;
    action_start_time = millis();
    if (enable_pin != -1) {
        digitalWrite(enable_pin, HIGH);
    }
    digitalWrite(closing_pin, LOW);
    digitalWrite(opening_pin, HIGH);
}

void DCDoor::run(JsonArray cmd) {
    const char* action = cmd[0]; // "open" or "close"
    if (strcmp(action, "open") == 0) {
        open();
    } else if (strcmp(action, "close") == 0) {
        close();
    } else {
        // Handle error or other actions
    }
}

void DCDoor::get_value(JsonDocument* container){
    container->set(nullptr);
}