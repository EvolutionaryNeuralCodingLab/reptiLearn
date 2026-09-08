# Interface documentation

This document describes the available arena controller interface types and their configuration parameters. 
See [Setting up the arena controller](arena_setup.md) for more information.

## Common interface attributes

- name: Interface name for identification. NOTE: Interface names should be unique across all connected boards.
- type: The interface type. Currently one of `line trigger feeder dcdoor dallas_temperature mux lis3mdl tmag5273 magnets`. Each one is explained below.
- ui: Determines how this interface is controlled in the ReptiLearn user interface.

## Interface types and attributes
There are a number of supported interfaces. The `"type"` attribute determines which one is used.

### `line`
Control a single digital output pin. Useful for turning things on and off.

Attributes:
- `pin`: Integer. The Arduino digital pin number to use.
- `reverse`: true | false. Reverse the line output. Will output HIGH when its  state is 0 and LOW when it is 1. 

Commands:
- `get`: Sends back the current state of the line - 0 or 1.
- `toggle`: Set the line state to the opposite of the current one.
- `set <x>`: Set the line state to <x> (0 or 1)
- `periodic <0|1> <period_dur>`: Control toggling the line on and off at a fixed rate. For example `periodic 1 500` will start toggling every 500 ms. `periodic 0` will stop the toggling. The period can be reliably timed at quite short durations. This is useful for blinking LEDs, etc.

Example:
```json
{
    "name": "LED",
    "type": "line",
    "pin": 12,
    "ui": "toggle"
},
```

### `trigger`
Output pulses at a fixed frequency on a single pin. This is used for synchronizing frame acquistion of multiple cameras.

Attributes:
- `pin`: Integer. The Arduino digital pin number to use.
- `pulse_len`: Integer. Time duration in milliseconds between successive pulses. For example, to acquire frames at 20 frames per second this attribute should be 50.
- `pulse_width`: Float. A number between 0 and 1. The pulse duty cycle. The fraction of the pulse period in which the output will be on. For example, a value of 0.8 with a pulse_len of 50ms will result in the digital pin going HIGH for 40ms and then LOW for 10ms before going HIGH again.

Commands:
Like the `line` interface, the `trigger` interface inherits from the toggle interface and has the same commands (`get`, `set`, `toggle`, `periodic`). See the line interface documentation.

Example:
```json
{
    "name": "Camera Trigger",
    "type": "trigger",
    "pin": 12,
    "pulse_len": 17,
    "pulse_width": 0.7,
    "ui": "camera_trigger"
}
```

### `feeder`
Control an EVNICE EV200GW fish feeder (or similar)

Attributes:
- `pins`: Array of 4 integers. The numbers of the pins that are connected to the ULN2003 board.

Commands:
- `dispense`: Dispense one reward from the feeder.

Example:
```json
{
    "name": "Right Feeder",
    "type": "feeder",
    "pins": [5, 6, 7, 8],
    "ui": "action",
    "command": "dispense",
    "icon": "gift"
}
```

### `dcdoor`
DC solenoid doors controlled by open/close pins. Sends timed pulses to drive the door mechanism.

Attributes:
- `open_pin`: Integer. Arduino pin for the open direction.
- `close_pin`: Integer. Arduino pin for the close direction.

Commands:
- `open`: Pulse the open pin (door opens).
- `close`: Pulse the close pin (door closes).

Example:
```json
{
    "name": "Right Door",
    "type": "dcdoor",
    "open_pin": 2,
    "close_pin": 3,
    "ui": "action",
    "command": "open",
    "icon": "door-open"
}
```

### `tmag5273`
Read magnetic field from a Texas Instruments TMAG5273 3-axis Hall sensor (SparkFun breakout). Requires the [SparkFun TMAG5273 Arduino Library](https://github.com/sparkfun/SparkFun_TMAG5273_Arduino_Library) to be installed in the Arduino IDE / arduino-cli.

The sensor is configured for continuous measurement with a ±40 mT range and 32× conversion averaging (same defaults as the SparkFun basic example). Values are reported in microTesla (µT).

Attributes:
- `i2c_address`: Optional integer. I2C address of the sensor (default `34`, i.e. `0x22`). Set a unique address per sensor when multiple TMAG5273 devices share one bus.
- `auto_poll_ms`: Optional integer. When set (e.g. `5000`), the interface automatically publishes updated readings over serial at this interval, in addition to responding to `get` commands from ReptiLearn.

Commands:
- `get`: Sends back `[x, y, z, |B|]` in µT (x, y, z components and total field magnitude).

Example:
```json
{
    "name": "Magnetic Field",
    "type": "tmag5273",
    "auto_poll_ms": 5000,
    "ui": "sensor",
    "unit": " µT",
    "icon": "magnet"
}
```

To log readings to the database, add a `data_log` section under `arena` in your system config (see `system/config/config.py` for the format). Column names follow flattened interface values, e.g. `Magnetic Field_0` … `Magnetic Field_3` for x, y, z, and |B|. Rows are written when the arena polls (`poll_interval`) and when the Arduino sends updates (e.g. with `auto_poll_ms`).

To show readings on the **live video stream** (like the timestamp), enable `magnetic_sensor_overlay` in `system/config/config.py` (the `interface` name must match the arena interface `name`). The overlay reads the same arena values and draws them on configured `image_sources`, by default just above the date/time stamp at the bottom of the frame.

### `dallas_temperature`
Communicate with digital temperature sensors such as DS18B20 (one-wire protocol). This uses the DallasTemperature arduino library. Check the [library documentation](https://github.com/milesburton/Arduino-Temperature-Control-Library) for supported devices. This interface can control any number of such sensors connected in parallel over a single Arduino digital pin.

Attributes:
- `pin`: Integer. The one-wire digital pin number. 

Commands:
- `get`: Sends back an array of floats containing the current measurement of each sensor.

Example:
```json
{
    "name": "Temp",
    "type": "dallas_temperature",
    "pin": 2,
    "ui": "sensor",
    "unit": "°",
    "icon": "thermometer-half"
}
```

## Interface UIs
The `ui` attribute determines how the interface is presented in the Arena menu of the ReptiLearn UI. Each `ui` type can have additional interface attributes that configure how it will be displayed in the menu.

### `toggle`

A toggle button that allows setting the interface on or off. It has no additional attributes.

Compatible interfaces: `line`

### `trigger`
This `ui` value tells ReptiLearn to use this interface as a camera trigger. The trigger can be controlled from the trigger button next to the recording button in the UI, or automatically when starting and stopping video recording (in case the trigger was not already running before recording). There are no additional attributes.

Only one interface with the `trigger` ui is supported. Additional interfaces will be ignored by the recording system.

Compatible interfaces: `trigger`

### `action`

A button that sends a command without arguments to the interface. This can be any command.

Attributes:
- `command`: String. The command name. For example, for controlling a `feeder` interface manually it should be set to `dispense`.
- `icon`: String. A name of a FontAwesome icon that will be displayed on the button. See [here](https://fontawesome.com/search?o=r&m=free) for available icons.

Compatible interfaces: any interface that has commands without arguments (e.g. `feeder`)

### `sensor`

Displays the sensor reading, possibly listing multiple sensors that send on the same interface (as in the `dallas_temperature` interface).

Attributes:
- `unit`: String. The units of the sensor value.
- `icon`: String. A name of a FontAwesome icon that will be displayed on the button. See [here](https://fontawesome.com/search?o=r&m=free) for available icons.

Compatible interfaces: `dallas temperature` (but can be used to display the value of any interface).
