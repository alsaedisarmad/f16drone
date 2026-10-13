# -*- coding: utf-8 -*-
# درون تجريبي (محاكاة) + سيرفر بسيط للوحة التحكم
# رسائل السجل تُرسل كمفاتيح (armed, takeoff...) واللوحة تترجمها حسب اللغة
# التشغيل:  python drone.py   ثم افتح  http://localhost:8080
import json, math, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
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
        self.log = ["-- ready"]
        self.lock = threading.Lock()

    def say(self, msg):
        self.log.append(time.strftime("%H:%M:%S ") + msg)
        self.log = self.log[-15:]

    def command(self, c, v=None):
        with self.lock:
            if c == "arm":
                self.armed = True; self.say("armed")
            elif c == "disarm":
                if self.flying: self.say("arm_in_flight"); return
                self.armed = False; self.say("disarmed")
            elif c == "takeoff":
                if not self.armed: self.say("arm_first"); return
                self.flying = True; self.target_alt = 10; self.say("takeoff")
            elif c == "land":
                self.target_alt = 0; self.say("landing")
            elif c in ("forward", "back", "left", "right"):
                if not self.flying: self.say("on_ground"); return
                a = math.radians(self.heading + {"forward": 0, "right": 90, "back": 180, "left": 270}[c])
                self.x += math.sin(a) * self.speed
                self.y += math.cos(a) * self.speed
                self.say("move " + c)
            elif c == "up" and self.flying:
                self.target_alt = min(self.target_alt + 2, 120)
            elif c == "down" and self.flying:
                self.target_alt = max(self.target_alt - 2, 1)
            elif c == "yaw_l":
                self.heading = (self.heading - 15) % 360
            elif c == "yaw_r":
                self.heading = (self.heading + 15) % 360
            elif c == "speed" and v:
                self.speed = max(0.5, min(float(v), 15)); self.say(f"speed {self.speed}")
            elif c == "home":
                self.x = self.y = 0; self.say("home")
            elif c == "stop":
                self.flying = False; self.armed = False; self.alt = 0; self.target_alt = 0
                self.say("estop")

    def tick(self):
        while True:
            with self.lock:
                if self.flying:
                    self.alt += (self.target_alt - self.alt) * 0.2
                    self.battery = max(0, self.battery - 0.05)
                    if self.target_alt == 0 and self.alt < 0.1:
                        self.alt = 0; self.flying = False; self.say("landed")
                    if self.battery < 15 and self.target_alt != 0:
                        self.target_alt = 0; self.say("low_bat")
            time.sleep(0.2)

    def status(self):
        with self.lock:
            return {k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in self.__dict__.items() if k != "lock"}


drone = Drone()
ROOT = Path(__file__).parent
TYPES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}


def aircraft(lat, lon, dist):
    """طائرات حقيقية قريبة من مصدر مفتوح (ADS-B): adsb.lol ثم OpenSky كاحتياط"""
    try:
        url = f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
        ac = json.load(urlopen(Request(url, headers={"User-Agent": "f16drone"}), timeout=10)).get("ac", [])
        return [{"id": a.get("hex"), "call": (a.get("flight") or a.get("r") or "").strip(), "lat": a["lat"], "lon": a["lon"],
                 "alt": round((a.get("alt_baro") if isinstance(a.get("alt_baro"), (int, float)) else 0) * 0.3048),
                 "trk": a.get("track") or 0, "spd": round((a.get("gs") or 0) * 1.852)}
                for a in ac if "lat" in a]
    except Exception:
        d = dist / 60
        url = f"https://opensky-network.org/api/states/all?lamin={lat-d}&lamax={lat+d}&lomin={lon-d}&lomax={lon+d}"
        st = json.load(urlopen(url, timeout=10)).get("states") or []
        return [{"id": a[0], "call": (a[1] or "").strip(), "lat": a[6], "lon": a[5], "alt": round(a[7] or 0),
                 "trk": a[10] or 0, "spd": round((a[9] or 0) * 3.6)} for a in st if a[5] is not None]


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
        elif u.path == "/aircraft":
            try:
                lat, lon = float(q["lat"][0]), float(q["lon"][0])
                self.send(json.dumps(aircraft(lat, lon, int(q.get("dist", ["40"])[0]))))
            except Exception as e:
                self.send(json.dumps({"error": str(e)}))
        else:
            f = (ROOT / (u.path.strip("/") or "index.html")).resolve()
            if f.parent != ROOT.resolve() or not f.is_file():
                f = ROOT / "index.html"
            self.send(f.read_text(encoding="utf-8"), TYPES.get(f.suffix, "text/plain"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=drone.tick, daemon=True).start()
    print("لوحة التحكم: http://localhost:8080")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
