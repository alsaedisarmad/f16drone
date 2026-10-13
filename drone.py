# -*- coding: utf-8 -*-
# درون تجريبي (محاكاة) + سيرفر بسيط للوحة التحكم
# التشغيل:  python drone.py   ثم افتح  http://localhost:8080
import json, math, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path


class Drone:
    def __init__(self):
        self.armed = False
        self.flying = False
        self.alt = 0.0          # الارتفاع (متر)
        self.x = 0.0            # الموقع (متر)
        self.y = 0.0
        self.heading = 0        # الاتجاه (درجة)
        self.speed = 2.0        # السرعة (م/ث)
        self.battery = 100.0
        self.target_alt = 0.0
        self.log = ["النظام جاهز"]
        self.lock = threading.Lock()

    def say(self, msg):
        self.log.append(time.strftime("%H:%M:%S ") + msg)
        self.log = self.log[-15:]

    def command(self, c, v=None):
        with self.lock:
            if c == "arm":
                self.armed = True; self.say("تم تشغيل المحركات")
            elif c == "disarm":
                if self.flying: self.say("لا يمكن الإيقاف أثناء الطيران"); return
                self.armed = False; self.say("تم إيقاف المحركات")
            elif c == "takeoff":
                if not self.armed: self.say("شغّل المحركات أولاً"); return
                self.flying = True; self.target_alt = 10; self.say("إقلاع إلى 10 م")
            elif c == "land":
                self.target_alt = 0; self.say("جارِ الهبوط")
            elif c in ("forward", "back", "left", "right"):
                if not self.flying: self.say("الدرون على الأرض"); return
                a = math.radians(self.heading + {"forward": 0, "right": 90, "back": 180, "left": 270}[c])
                self.x += math.sin(a) * self.speed
                self.y += math.cos(a) * self.speed
                self.say("تحرك: " + c)
            elif c == "up" and self.flying:
                self.target_alt = min(self.target_alt + 2, 120)
            elif c == "down" and self.flying:
                self.target_alt = max(self.target_alt - 2, 1)
            elif c == "yaw_l":
                self.heading = (self.heading - 15) % 360
            elif c == "yaw_r":
                self.heading = (self.heading + 15) % 360
            elif c == "speed" and v:
                self.speed = max(0.5, min(float(v), 15)); self.say(f"السرعة = {self.speed} م/ث")
            elif c == "home":
                self.x = self.y = 0; self.say("العودة للنقطة الأساسية")
            elif c == "stop":
                self.flying = False; self.armed = False; self.alt = 0; self.target_alt = 0
                self.say("!!! إيقاف طوارئ !!!")

    def tick(self):
        while True:
            with self.lock:
                if self.flying:
                    self.alt += (self.target_alt - self.alt) * 0.2
                    self.battery = max(0, self.battery - 0.05)
                    if self.target_alt == 0 and self.alt < 0.1:
                        self.alt = 0; self.flying = False; self.say("تم الهبوط")
                    if self.battery < 15 and self.target_alt != 0:
                        self.target_alt = 0; self.say("بطارية ضعيفة - هبوط تلقائي")
            time.sleep(0.2)

    def status(self):
        with self.lock:
            return {k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in self.__dict__.items() if k != "lock"}


drone = Drone()
PANEL = Path(__file__).with_name("index.html")


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/status":
            self.send(json.dumps(drone.status(), ensure_ascii=False))
        elif u.path == "/cmd":
            drone.command(q.get("c", [""])[0], q.get("v", [None])[0])
            self.send(json.dumps(drone.status(), ensure_ascii=False))
        else:
            self.send(PANEL.read_text(encoding="utf-8"), "text/html")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=drone.tick, daemon=True).start()
    print("لوحة التحكم: http://localhost:8080")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
