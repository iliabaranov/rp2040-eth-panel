"""ROS 2 driver for the RP2040-ETH operator panel (2 buttons, 2 LED rings).

Connects as a TCP client to the panel's line-delimited JSON server. The CH9120
bridge supports exactly ONE client: do not run tools/panel_live.py and this
driver at the same time.

Published (latched: RELIABLE + TRANSIENT_LOCAL, depth 10):
  ~/button1/pressed, ~/button2/pressed (std_msgs/Bool)
      Initial state from the hello line, then every down/up edge. Depth 10 (not 1)
      so a rapid press/release burst isn't coalesced before a subscriber reads it;
      TRANSIENT_LOCAL still latches recent samples for late joiners.

Subscribed:
  ~/ring1/color, ~/ring2/color (std_msgs/ColorRGBA)
      r,g,b in 0..1; **a is BRIGHTNESS in 0..1 — a=0.0 means OFF**.
      ColorRGBA defaults a to 0.0, so senders must set it explicitly.
  ~/button1/light (std_msgs/Bool) — the illuminated button's lamp.

Desired-state resync: the last commanded ring colors and lamp state are cached
and re-sent on every hello (each (re)connect — device reboot, OTA, cable blip),
so the panel always converges to ROS's desired state. The driver waits ~1 s
for the device's unsolicited connect-time hello, then REQUESTS one with
{"cmd":"hello"} if it hasn't arrived: some CH9120 batches never assert the
TCP-status pin that triggers it (fw >= 1.0.3 answers the request). The request
is a fallback, not sent immediately, because on TCPS-working units the device
flushes its RX buffer at the connect edge and a request already in flight gets
truncated to a junk line (the device then errs "no cmd").

Liveness: the CH9120 serves ONE client and silently drops a displaced one (no
FIN/RST), leaving a half-open socket that recv()-timeouts forever while sends
vanish into the local TCP buffer. The driver therefore pings whenever the link
has been quiet and declares the connection dead if NOTHING IS RECEIVED for
liveness_timeout — received traffic is the only liveness evidence; successful
sends prove nothing. On a dead connection it reconnects and the hello resync
replays desired state, so recovery needs no manual restart.

Parameters:
  host (str, '')          device IP (DHCP-assigned). REQUIRED.
  port (int, 5005)        device TCP port
  reconnect_period (s)    delay between reconnect attempts
  keepalive_period (s)    ping the device after this much RX silence (2.0)
  liveness_timeout (s)    declare the connection dead after this much RX
                          silence and reconnect (6.0)
"""
import socket
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy)
from std_msgs.msg import Bool, ColorRGBA

from panel_driver.panel_protocol import (
    color_rgba_to_bytes, fmt_hello_cmd, fmt_lamp_cmd, fmt_ping_cmd,
    fmt_ring_cmd, parse_event,
)

RING_IDS = (1, 2)


class PanelDriver(Node):
    def __init__(self):
        super().__init__("panel_driver")
        self.declare_parameter("host", "")
        self.declare_parameter("port", 5005)
        self.declare_parameter("reconnect_period", 2.0)
        self.declare_parameter("keepalive_period", 2.0)
        self.declare_parameter("liveness_timeout", 6.0)

        self.host = str(self.get_parameter("host").value or "")
        self.port = int(self.get_parameter("port").value)
        self.reconnect_period = float(self.get_parameter("reconnect_period").value)
        self.keepalive_period = float(self.get_parameter("keepalive_period").value)
        self.liveness_timeout = float(self.get_parameter("liveness_timeout").value)
        if self.liveness_timeout < 2 * self.keepalive_period:
            self.get_logger().warn(
                f"liveness_timeout ({self.liveness_timeout:g}s) < 2x "
                f"keepalive_period ({self.keepalive_period:g}s) — a single "
                "lost ping will force a reconnect; consider widening it"
            )

        if not self.host:
            self.get_logger().fatal(
                "parameter 'host' is empty — the panel's IP is DHCP-assigned, "
                "so there is no sensible default. Set it with:\n"
                "  ros2 run panel_driver panel_driver --ros-args -p host:=<device-ip>\n"
                "  ros2 launch panel_driver panel_driver.launch.py host:=<device-ip>\n"
                "Not connecting; node will exit."
            )
            return

        # Latched button state: late subscribers immediately get current state.
        # Depth 10 (not 1) so a quick press+release burst isn't coalesced away
        # before a subscriber reads it; TRANSIENT_LOCAL keeps the latch behaviour.
        latched = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._btn_pubs = {
            1: self.create_publisher(Bool, "~/button1/pressed", latched),
            2: self.create_publisher(Bool, "~/button2/pressed", latched),
        }

        for ring_id in RING_IDS:
            self.create_subscription(
                ColorRGBA, f"~/ring{ring_id}/color",
                lambda msg, rid=ring_id: self._on_ring(rid, msg), 10)
        self.create_subscription(Bool, "~/button1/light", self._on_lamp, 10)

        # Desired-state cache; re-sent on every hello so the panel converges
        # to ROS's view after reboots / OTA / cable blips.
        self._ring_cmds: dict[int, str | None] = {rid: None for rid in RING_IDS}
        self._lamp_cmd: str | None = None
        self._a_zero_warned = False  # warn once about a=0 (ColorRGBA default), not per-msg

        # The socket is owned by the reader thread; subscription callbacks run
        # in the executor thread and send through it. _sock_lock serializes
        # sends and guards the handle; send-while-disconnected just updates the
        # cache (the hello resync covers it).
        self._sock = None
        self._sock_lock = threading.Lock()

        self.get_logger().info(f"panel_driver -> {self.host}:{self.port}")

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    # ---- TCP client (reader thread owns the socket) ----

    def _reader_loop(self):
        while not self._stop.is_set():
            try:
                try:
                    with socket.create_connection((self.host, self.port),
                                                  timeout=5) as s:
                        self.get_logger().info(
                            f"connected to {self.host}:{self.port}")
                        s.settimeout(0.5)
                        with self._sock_lock:
                            self._sock = s
                        # Hello fallback: TCPS-dead CH9120 batches never send
                        # the connect-time hello, so request one — but only
                        # after a grace period. Sent immediately, the request
                        # races the device's connect-edge RX flush on
                        # TCPS-working units and arrives truncated.
                        self._hello_seen = False
                        hello_requested = False
                        t_conn = time.monotonic()
                        # Liveness feeds on RECEIVED lines only: a displaced
                        # client keeps send()ing into its half-open socket
                        # successfully for minutes, so sends prove nothing.
                        last_rx = t_conn
                        last_ping = 0.0
                        buf = b""
                        while not self._stop.is_set():
                            try:
                                data = s.recv(256)
                                if not data:
                                    raise ConnectionError(
                                        "peer closed connection")
                                last_rx = time.monotonic()
                                buf += data
                                while b"\n" in buf:
                                    line, buf = buf.split(b"\n", 1)
                                    self._handle_line(
                                        line.decode("utf-8", "replace"))
                            except socket.timeout:
                                pass
                            now = time.monotonic()
                            if now - last_rx >= self.liveness_timeout:
                                raise ConnectionError(
                                    f"nothing received for "
                                    f"{self.liveness_timeout:g}s — connection "
                                    "dead or displaced by another client")
                            if (now - last_rx >= self.keepalive_period
                                    and now - last_ping
                                        >= self.keepalive_period):
                                last_ping = now
                                self._send(fmt_ping_cmd())
                            if (not self._hello_seen and not hello_requested
                                    and now - t_conn >= 1.0):
                                hello_requested = True
                                self._send(fmt_hello_cmd())
                finally:
                    with self._sock_lock:
                        self._sock = None
            except Exception as e:  # noqa: BLE001 - keep the driver alive
                if self._stop.is_set():
                    break
                self.get_logger().warn(
                    f"connection issue ({e}); retrying in "
                    f"{self.reconnect_period:g}s"
                )
                time.sleep(self.reconnect_period)

    def _handle_line(self, line: str):
        ev = parse_event(line)
        if ev is None:
            return
        t = ev["t"]
        if t == "btn":
            self._publish_button(ev["id"], ev["e"] == "down")
        elif t == "hello":
            self._hello_seen = True
            self.get_logger().info(
                f"panel hello: fw={ev['fw']} ip={ev['ip']} "
                f"pressed={ev['pressed']}"
            )
            for i, pressed in enumerate(ev["pressed"]):
                self._publish_button(i + 1, pressed)
            self._resync()
        elif t == "ack":
            self.get_logger().debug(f"ack: {ev['cmd']}")
        elif t == "err":
            self.get_logger().warn(f"device error: {ev['msg']}")

    def _publish_button(self, btn_id: int, pressed: bool):
        pub = self._btn_pubs.get(btn_id)
        if pub is None:
            self.get_logger().warn(f"button event for unknown id {btn_id}")
            return
        pub.publish(Bool(data=pressed))

    # ---- Host -> device commands (executor thread) ----

    def _on_ring(self, ring_id: int, msg: ColorRGBA):
        r8, g8, b8, br8 = color_rgba_to_bytes(msg.r, msg.g, msg.b, msg.a)
        if br8 == 0 and not self._a_zero_warned:
            self._a_zero_warned = True
            self.get_logger().warn(
                f"ring{ring_id}: a -> brightness 0 (OFF). The a channel is "
                "brightness; ColorRGBA defaults it to 0 — set it explicitly. "
                "(This warning is shown once.)"
            )
        line = fmt_ring_cmd(ring_id, r8, g8, b8, br8)
        self._ring_cmds[ring_id] = line
        self._send(line)

    def _on_lamp(self, msg: Bool):
        line = fmt_lamp_cmd(bool(msg.data))
        self._lamp_cmd = line
        self._send(line)

    def _send(self, line: str):
        """Send one command line; if disconnected, the cache alone suffices
        (resync on the next hello replays it)."""
        with self._sock_lock:
            s = self._sock
            if s is None:
                self.get_logger().debug(
                    "not connected; command cached for resync")
                return
            try:
                s.sendall(line.encode("utf-8"))
            except OSError as e:
                # A partial/failed write may have left a half-line on the wire,
                # corrupting framing. Tear the connection down so the reader loop
                # reconnects and _resync() replays the cache onto a clean stream.
                self.get_logger().warn(
                    f"send failed ({e}); dropping connection to resync")
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _resync(self):
        """Replay all cached desired state (called on every hello)."""
        sent = 0
        for ring_id in RING_IDS:
            cmd = self._ring_cmds[ring_id]
            if cmd is not None:
                self._send(cmd)
                sent += 1
        if self._lamp_cmd is not None:
            self._send(self._lamp_cmd)
            sent += 1
        if sent:
            self.get_logger().info(f"resynced {sent} cached command(s)")

    def destroy_node(self):
        if hasattr(self, "_stop"):
            self._stop.set()
        # Unblock the reader thread's recv() by tearing down the socket, then join
        # it so we don't leak a thread or race on shutdown.
        if hasattr(self, "_sock_lock"):
            with self._sock_lock:
                s = self._sock
                self._sock = None
            if s is not None:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    s.close()
                except OSError:
                    pass
        t = getattr(self, "_thread", None)
        if t is not None:
            t.join(timeout=2.0)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PanelDriver()
    try:
        if node.host:  # empty host: fatal already logged, exit cleanly
            rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # Ctrl-C / SIGTERM: normal shutdown, no traceback
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
