# -*- coding: utf-8 -*-

import json
import logging
import re
import threading
import ssl
import certifi
import time

import websocket

from custom_components.smarthomesec.const import API_BASEHOST

LOG = logging.getLogger(__name__)

# Demp støy fra websocket-biblioteket
logging.getLogger("websocket").setLevel(logging.CRITICAL)


class WSClient(threading.Thread):
    """WebSocket client for SmartHomeSec (Socket.IO EIO=4)."""

    global_wsc = None
    global_stop = False

    def __init__(self, client, token):
        LOG.debug("WSClient initializing...")

        self.client = client
        self.token = token

        self.wsc = None
        self.stop = False
        # Siste endring
        self.last_activity = time.time()
        self.connected_at = None

        # Track siste event og connect-tid for watchdog
        self._last_connect = time.time()
        self._last_event = time.time()

        super().__init__(daemon=True)

    # ----------------------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------------------

    def start(self):
        LOG.debug("WSClient thread starting")
        super().start()

    def stop_client(self):
        LOG.debug("WSClient stopping...")

        self.stop = True
        self.global_stop = True

        if self.wsc is not None:
            try:
                self.wsc.close()
            except Exception:
                pass

        self.global_wsc = None

    # ----------------------------------------------------------------------
    # INTERNAL
    # ----------------------------------------------------------------------

    def run(self):
        """WebSocket loop with adaptive reconnect (single owner)."""

        base = API_BASEHOST.rstrip("/")
        wsc_url = (
            f"wss://{base}/ws/socket.io/"
            f"?token={self.token}&transport=websocket&EIO=4"
        )

        LOG.debug("WebSocket URL: %r", wsc_url)

        # Close previous global WS if any
        if self.global_wsc is not None:
            try:
                self.global_wsc.close()
            except Exception:
                pass

        reconnect_delay = 2
        forced_login = False

        while not self.stop:

            LOG.debug("WebSocket: run_forever() starting")

            self.wsc = websocket.WebSocketApp(
                wsc_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_ping=self._on_ping,
                on_pong=self._on_pong,
                on_open=self._on_open,
            )

            self.global_wsc = self.wsc

            # ✅ Run connection (blocking)
            self.wsc.run_forever(
                ping_interval=20,
                ping_timeout=10,
                sslopt={"ca_certs": certifi.where()},
            )

            LOG.debug("WebSocket: run_forever() exited")

            if self.stop:
                break

            now = time.time()
            lived = now - getattr(self, "_last_connect", now)
            LOG.debug("WebSocket lived %s", lived)

            # --------------------------------------------------
            # 🔥 Watchdog (beholdt)
            # --------------------------------------------------
            if hasattr(self, "_last_event"):
                silent_for = time.time() - self._last_event
                since_connect = time.time() - getattr(self, "_last_connect", self._last_event)

                if silent_for > 21600 and since_connect > 300:
                    LOG.warning(
                        "WS silent too long (%.0fs, since connect %.0fs) → forcing full login()",
                        silent_for,
                        since_connect,
                    )
                    forced_login = True
                    self.client.callback("ForceLogin", None)
                    break

            # --------------------------------------------------
            # 🔥 Adaptive reconnect (behold)
            # --------------------------------------------------
            if lived > 10:
                reconnect_delay = 2
            else:
                reconnect_delay = min(reconnect_delay * 2, 30)

            LOG.debug("WebSocket reconnect in %s seconds...", reconnect_delay)

            # ✅ VIKTIG: pause før reconnect
            for _ in range(reconnect_delay):
                if self.stop:
                    break
                time.sleep(1)

        LOG.debug("WebSocket stopped")

        # ✅ Kun signal – IKKE start WS her
        if not forced_login:
            LOG.debug("WS stopped normally (no callback restart)")

    # ----------------------------------------------------------------------
    # EVENT HANDLERS
    # ----------------------------------------------------------------------

    def _on_open(self, ws):
        # Ny connect → nullstill "stillhet"
        self._last_connect = time.time()
        self._last_event = self._last_connect

        LOG.debug("WebSocket connected")
        self.connected_at = self._last_connect
        self.last_activity = self.connected_at

        # Socket.IO CONNECT frame
        try:
            ws.send("40")
            LOG.debug("Sent Socket.IO CONNECT (40)")
        except Exception as e:
            LOG.error("Failed to send CONNECT: %s", e)

        # Ingen AUTH – SmartHomeSec bruker token i URL
        self.client.callback("WebSocketConnect", None)

    def _on_error(self, ws, error):
        # opcode=8 er NORMAL disconnect fra SmartHomeSec
        if "opcode=8" in str(error):
            LOG.debug("WebSocket closed normally: %s", error)
            return

        LOG.warning("WebSocket error: %s", error)
        self.client.callback("WebSocketError", error)

    def _on_ping(self, ws, message):
        LOG.debug("WebSocket ping received")

    def _on_pong(self, ws, message):
        LOG.debug("WebSocket pong received")

    def _on_message(self, ws, message):
        """
        SmartHomeSec bruker Socket.IO framing:
        - "42" prefix = event
        - "3" = ping/pong
        - "0" = connect
        """
        self.last_activity = time.time()
        match = re.search(r"^(\d+)(.*)$", message)
        if not match:
            LOG.debug("WS: unparsed message: %s", message)
            return

        code = match.group(1)
        content = match.group(2)

        if code == "42":
            # 42 = faktisk event (dør, PIR, mode change osv.)
            # Brukes av watchdog til å vite at linja lever.
            self._last_event = time.time()

        LOG.debug("WS received: code=%s content=%s", code, content)

        # Send videre til coordinator
        self.client.callback(code, content)
