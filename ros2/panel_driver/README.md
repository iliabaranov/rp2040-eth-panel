# panel_driver (ROS 2 Humble)

ROS 2 **Humble** (`rclpy`) driver for the RP2040-ETH operator panel (2 illuminated
buttons, 2×16 WS2812 LED rings). Connects as a TCP client to the device's
line-delimited JSON server and bridges it to ROS topics in both directions.

> **Single TCP client only.** The CH9120 Ethernet bridge wedges if a second
> client connects. Do **not** run `tools/panel_live.py` (or any other tool
> talking to port 5005) while this driver is running.

## Topics

All names are node-relative (`~/...`); with the default node name they appear
under `/panel_driver/...`.

### Published

| topic | type | QoS | meaning |
|-------|------|-----|---------|
| `~/button1/pressed` | `std_msgs/Bool` | RELIABLE, TRANSIENT_LOCAL, depth 1 | button 1 state (latched) |
| `~/button2/pressed` | `std_msgs/Bool` | RELIABLE, TRANSIENT_LOCAL, depth 1 | button 2 state (latched) |

Button states are **latched**: late subscribers immediately receive the current
state. Initial states come from the device's `hello` line (sent on every
connect); after that, every `down`/`up` edge is published.

### Subscribed

| topic | type | meaning |
|-------|------|---------|
| `~/ring1/color` | `std_msgs/ColorRGBA` | ring 1 color + brightness |
| `~/ring2/color` | `std_msgs/ColorRGBA` | ring 2 color + brightness |
| `~/button1/light` | `std_msgs/Bool` | button 1 lamp (the illuminated button) |

> **⚠ The `a` channel is BRIGHTNESS, and it defaults to 0.0!**
> `r`, `g`, `b` are 0..1; `a` is brightness 0..1 where **`a=0` means the ring
> is OFF**. `ColorRGBA` zero-initializes `a`, so a sender that only sets
> `r/g/b` turns the ring off. Always set `a` explicitly (e.g. `a: 1.0`).

## Desired-state resync

The driver caches the last commanded ring colors and lamp state. On every
`hello` — i.e. every (re)connect, which covers device reboots, OTA updates and
cable blips — it re-sends all cached commands, so the panel always converges to
ROS's desired state. Commands published while disconnected are cached and
applied on the next reconnect.

## Parameters

| param | default | meaning |
|-------|---------|---------|
| `host` | `''` | device IP (DHCP-assigned). **Required** — the node logs a fatal error and exits if empty. |
| `port` | `5005` | device TCP port |
| `reconnect_period` | `2.0` | seconds between reconnect attempts |

## Run

```bash
# In a ROS 2 Humble workspace (ros2/ as the src dir):
source /opt/ros/humble/setup.bash
colcon build --packages-select panel_driver
source install/setup.bash

ros2 launch panel_driver panel_driver.launch.py host:=<device-ip>
# or:
ros2 run panel_driver panel_driver --ros-args -p host:=<device-ip>
```

Watch the buttons (latched — you get the current state immediately):

```bash
ros2 topic echo /panel_driver/button1/pressed
```

Set ring 1 to orange at half brightness (note `a` is set!):

```bash
ros2 topic pub --once /panel_driver/ring1/color std_msgs/msg/ColorRGBA \
  "{r: 1.0, g: 0.25, b: 0.0, a: 0.5}"
```

Turn the button lamp on:

```bash
ros2 topic pub --once /panel_driver/button1/light std_msgs/msg/Bool "{data: true}"
```

## Tests

The protocol logic is a pure module ([`panel_driver/panel_protocol.py`](panel_driver/panel_protocol.py),
no `rclpy` import) and is unit-tested without a ROS graph. Run the tests with a
clean environment — a sourced ROS env injects pytest plugins that break
collection:

```bash
cd ros2/panel_driver
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest test/
```
