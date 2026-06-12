#!/usr/bin/env python3
"""Standalone ROS 2 driver for the RP2040-ETH panel — the simplest thing that works.

Run it directly. No colcon build, no package install, no launch file:

    source /opt/ros/humble/setup.bash
    python3 examples/standalone_panel_driver.py <device-ip>      # e.g. 192.0.2.50

It connects to the panel (TCP, port 5005, line-delimited JSON), then:

  PUBLISHES button presses                         (std_msgs/Bool)
      /button1_pressed   /button2_pressed          True = down, False = up

  SUBSCRIBES to ring colour + lamp commands        (std_msgs/ColorRGBA, std_msgs/Bool)
      /ring1_color   /ring2_color                  r,g,b in 0..1; a = brightness 0..1
      /button1_light                               the illuminated button's lamp

Try it from another terminal (also `source /opt/ros/humble/setup.bash` there):

    ros2 topic echo /button1_pressed
    ros2 topic pub --once /ring1_color std_msgs/msg/ColorRGBA "{r: 1.0, g: 0.0, b: 0.0, a: 0.5}"
    ros2 topic pub --once /button1_light std_msgs/msg/Bool "{data: true}"

NOTE: the panel accepts ONE TCP client at a time. Don't run this and the full
panel_driver package (or tools/panel_live.py) against the same device at once.

This is a teaching example: ~100 lines, no reconnect/resync/QoS tuning. For the
production driver (auto-reconnect, desired-state resync on reboot, latched state,
clean shutdown) use the ros2/panel_driver package instead.
"""
import json
import socket
import sys
import threading

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, ColorRGBA

PORT = 5005


class PanelExample(Node):
    def __init__(self, host, port=PORT):
        super().__init__("panel_example")

        # One TCP connection to the panel. (Kept simple: if it isn't reachable,
        # create_connection raises and the program exits with the error.)
        self.sock = socket.create_connection((host, port), timeout=5)
        # create_connection's timeout stays on the socket; clear it so recv()
        # blocks until data arrives instead of raising socket.timeout after 5s of
        # no button activity (which would otherwise kill the reader thread).
        self.sock.settimeout(None)
        self.get_logger().info(f"connected to {host}:{port}")

        # Publishers: one Bool per button, True when pressed.
        self.btn_pubs = {
            1: self.create_publisher(Bool, "button1_pressed", 10),
            2: self.create_publisher(Bool, "button2_pressed", 10),
        }

        # Subscribers: ring colours and the lamp. Callbacks send a JSON command.
        self.create_subscription(ColorRGBA, "ring1_color",
                                 lambda m: self.set_ring(1, m), 10)
        self.create_subscription(ColorRGBA, "ring2_color",
                                 lambda m: self.set_ring(2, m), 10)
        self.create_subscription(Bool, "button1_light", self.set_lamp, 10)

        # Read button events from the panel in the background so rclpy.spin()
        # can run the subscription callbacks in the main thread.
        threading.Thread(target=self.read_loop, daemon=True).start()

    # ---- sending commands to the panel ----

    def send(self, obj):
        """Write one JSON command line to the panel."""
        self.sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def set_ring(self, ring_id, msg):
        # ColorRGBA channels are 0..1 floats; the panel wants 0..255 ints, and
        # the alpha channel carries brightness (a=0 means the ring is off).
        to255 = lambda x: max(0, min(255, round(x * 255)))
        self.send({"cmd": "ring", "id": ring_id,
                   "r": to255(msg.r), "g": to255(msg.g), "b": to255(msg.b),
                   "brightness": to255(msg.a)})
        self.get_logger().info(
            f"ring {ring_id} -> rgb({to255(msg.r)},{to255(msg.g)},"
            f"{to255(msg.b)}) brightness {to255(msg.a)}")

    def set_lamp(self, msg):
        self.send({"cmd": "lamp", "on": bool(msg.data)})
        self.get_logger().info(f"lamp -> {'on' if msg.data else 'off'}")

    # ---- receiving events from the panel ----

    def read_loop(self):
        buf = b""
        while rclpy.ok():
            try:
                data = self.sock.recv(256)
            except OSError:
                break
            if not data:
                break  # panel closed the connection
            buf += data
            while b"\n" in buf:  # the panel sends one JSON object per line
                line, buf = buf.split(b"\n", 1)
                self.handle_message(line.decode("utf-8", "replace"))

    def handle_message(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            return  # ignore anything that isn't valid JSON
        if msg.get("t") == "btn":
            pressed = msg["e"] == "down"
            self.btn_pubs[msg["id"]].publish(Bool(data=pressed))
            self.get_logger().info(f"button {msg['id']} {msg['e']}")
        elif msg.get("t") == "hello":
            self.get_logger().info(f"panel hello: {line}")
        # "ack"/"err" replies are ignored in this example.


def main():
    if len(sys.argv) < 2:
        print("usage: python3 standalone_panel_driver.py <device-ip> [port]")
        sys.exit(1)
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    rclpy.init()
    node = PanelExample(host, port)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # Ctrl-C or SIGTERM: stop cleanly, no traceback
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
