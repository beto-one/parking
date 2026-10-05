import json
import threading
import time
import urllib.request
import webbrowser

import arabic_reshaper
from bidi.algorithm import get_display
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.storage.jsonstore import JsonStore
from kivy.uix.label import Label
from kivy.utils import platform
from os.path import join

# ---------------- settings ----------------
SERVER = ""                           # empty = no server needed (spots saved on this phone)
PAY_LINK = "https://daramet.com/Parking?webintent&donate=50000"  # payment link
BT_NAMES = ("HC-05", "HC-06", "HC", "JDY", "BT0", "HM-10", "Arduino")  # module name (or part of it)
FONT = "Persian.ttf"                  # font file next to main.py
DOOR_OPEN_SEC = 5
# ------------------------------------------


def fa(text):
    return get_display(arabic_reshaper.reshape(text))


class Bluetooth:
    """Sends one character to the HC-05 module over classic Bluetooth (Android)."""

    def __init__(self):
        self.out = None

    def connect(self):
        from jnius import autoclass
        adapter = autoclass("android.bluetooth.BluetoothAdapter").getDefaultAdapter()
        uuid = autoclass("java.util.UUID").fromString("00001101-0000-1000-8000-00805F9B34FB")
        for dev in adapter.getBondedDevices().toArray():
            name = dev.getName() or ""
            if any(k.lower() in name.lower() for k in BT_NAMES):
                sock = dev.createRfcommSocketToServiceRecord(uuid)
                adapter.cancelDiscovery()
                sock.connect()
                self.out = sock.getOutputStream()
                return True
        return False

    def send(self, ch):
        try:
            if self.out is None and not self.connect():
                return False
            self.out.write(ord(ch))
            self.out.flush()
            return True
        except Exception:
            self.out = None
            return False


class ParkingApp(App):
    title = "پارکینگ من"

    def build(self):
        if platform == "android":
            from android.permissions import request_permissions
            request_permissions([
                "android.permission.BLUETOOTH_CONNECT",
                "android.permission.BLUETOOTH_SCAN",
                "android.permission.ACCESS_FINE_LOCATION",
            ])
        self.bt = Bluetooth()
        self.store = JsonStore(join(self.user_data_dir, "parking.json"))
        self.sel = None       # selected spot
        self.spot = None      # my reserved spot
        self.end = 0.0        # end of my reservation (server time)
        self.state = "select"  # select / enter / parked / exit
        if self.store.exists("me"):
            me = self.store.get("me")
            self.spot, self.end, self.state = me["spot"], me["end"], me["state"]
        self.pending = None   # reserve / extend (waiting for payment confirmation)
        self.offset = 0.0     # server time - phone time
        self.ends = [0.0] * 6

        root = BoxLayout(orientation="vertical", padding=12, spacing=10)
        root.add_widget(Label(text=fa("پارکینگ من"), font_name=FONT, font_size=30, size_hint_y=0.12))
        self.status = Label(text="", font_name=FONT, font_size=18, size_hint_y=0.15)
        root.add_widget(self.status)

        grid = GridLayout(cols=3, spacing=8, size_hint_y=0.3)
        self.spot_btns = []
        for n in range(1, 7):
            b = Button(text=str(n), font_size=26)
            b.bind(on_press=lambda _b, n=n: self.choose(n))
            grid.add_widget(b)
            self.spot_btns.append(b)
        root.add_widget(grid)

        self.pay_btn = self.mk(root, "پرداخت", self.on_pay)
        self.paid_btn = self.mk(root, "پرداخت کردم", self.on_paid)
        self.door_btn = self.mk(root, "باز کردن درب", self.on_door)
        self.ext_btn = self.mk(root, "تمدید یک ساعت", self.on_extend)

        Clock.schedule_interval(lambda dt: self.refresh(), 5)
        Clock.schedule_interval(lambda dt: self.tick(), 1)
        self.refresh()
        self.update_ui()
        return root

    def mk(self, root, text, cb):
        b = Button(text=fa(text), font_name=FONT, font_size=20, size_hint_y=0.1)
        b.bind(on_press=lambda _b: cb())
        root.add_widget(b)
        return b

    # ---------- helpers ----------
    def now(self):
        return time.time() + self.offset

    def save(self):
        self.store.put("me", spot=self.spot, end=self.end, state=self.state)

    def local(self, path, data):
        """Works without a server: spots are saved on this phone."""
        ends = self.store.get("spots")["ends"] if self.store.exists("spots") else [0.0] * 6
        now = time.time()
        i = int((data or {}).get("spot") or 0) - 1
        res = {"ok": True}
        if path == "/spots":
            return {"now": now, "ends": ends}
        if not 0 <= i < 6:
            return {"ok": False}
        if path == "/reserve":
            if ends[i] > now:
                return {"ok": False, "reason": "taken"}
            ends[i] = now + 3600
        elif path == "/extend":
            ends[i] = max(ends[i], now) + 3600
        elif path == "/release":
            ends[i] = 0.0
        res["end"] = ends[i]
        self.store.put("spots", ends=ends)
        return res

    def api(self, path, data=None, cb=None):
        if not SERVER:
            res = self.local(path, data)
            if cb:
                Clock.schedule_once(lambda dt: cb(res))
            return

        def work():
            try:
                body = json.dumps(data).encode() if data is not None else None
                req = urllib.request.Request(
                    SERVER + path, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    res = json.loads(r.read())
            except urllib.error.HTTPError as e:
                try:
                    res = json.loads(e.read())
                except Exception:
                    res = {"ok": False}
            except Exception:
                res = {"ok": False, "reason": "net"}
            if cb:
                Clock.schedule_once(lambda dt: cb(res))
        threading.Thread(target=work, daemon=True).start()

    def say(self, text):
        self.status.text = fa(text)

    def refresh(self):
        self.api("/spots", cb=self.on_spots)

    def on_spots(self, res):
        if "ends" in res:
            self.offset = res["now"] - time.time()
            self.ends = res["ends"]
            self.update_ui()

    def choose(self, n):
        if self.state == "select":
            self.sel = n
            self.update_ui()

    # ---------- actions ----------
    def on_pay(self):
        if self.sel is None:
            return self.say("اول جای پارک را انتخاب کن")
        self.pending = "reserve"
        webbrowser.open(PAY_LINK)
        self.update_ui()

    def on_extend(self):
        self.pending = "extend"
        webbrowser.open(PAY_LINK)
        self.update_ui()

    def on_paid(self):
        if self.pending == "reserve":
            self.api("/reserve", {"spot": self.sel}, self.after_reserve)
        elif self.pending == "extend":
            self.api("/extend", {"spot": self.spot}, self.after_extend)

    def after_reserve(self, res):
        if res.get("ok"):
            self.spot, self.end, self.state, self.pending = self.sel, res["end"], "enter", None
            self.save()
        elif res.get("reason") == "taken":
            self.pending = None
            self.say("این جا همین الان پر شد، جای دیگری انتخاب کن")
        else:
            self.say("خطا در ارتباط با سرور")
        self.update_ui()

    def after_extend(self, res):
        if res.get("ok"):
            self.end, self.pending = res["end"], None
            if self.state == "exit":
                self.state = "parked"
            self.save()
        else:
            self.say("خطا در ارتباط با سرور")
        self.update_ui()

    def on_door(self):
        if self.state not in ("enter", "exit"):
            return

        def work():
            ok = self.bt.send("1")
            if ok:
                time.sleep(DOOR_OPEN_SEC)
                self.bt.send("0")
            Clock.schedule_once(lambda dt: self.after_door(ok))
        threading.Thread(target=work, daemon=True).start()

    def after_door(self, ok):
        if not ok:
            return self.say("اتصال بلوتوث برقرار نشد")
        if self.state == "enter":
            self.state = "parked"
        elif self.state == "exit":
            self.api("/release", {"spot": self.spot})
            self.spot, self.sel, self.state = None, None, "select"
        self.save()
        self.update_ui()

    def tick(self):
        if self.state == "parked" and self.now() >= self.end:
            self.state = "exit"
            self.save()
        self.update_ui()

    # ---------- UI ----------
    def update_ui(self):
        now = self.now()
        for i, b in enumerate(self.spot_btns):
            n = i + 1
            taken = self.ends[i] > now and n != self.spot
            b.disabled = taken or self.state != "select"
            if n == self.spot:
                b.background_color = (0.2, 0.5, 1, 1)
            elif taken:
                b.background_color = (0.9, 0.2, 0.2, 1)
            elif n == self.sel:
                b.background_color = (1, 0.8, 0.2, 1)
            else:
                b.background_color = (0.2, 0.8, 0.3, 1)

        s = self.state
        self.pay_btn.disabled = not (s == "select" and self.sel and not self.pending)
        self.paid_btn.disabled = self.pending is None
        self.door_btn.disabled = s not in ("enter", "exit")
        self.ext_btn.disabled = not (s in ("parked", "exit") and not self.pending)

        left = max(0, int(self.end - now))
        if s == "select":
            self.say("جای پارک را انتخاب کن و پرداخت کن" if self.sel is None else f"جای {self.sel} انتخاب شد")
        elif s == "enter":
            self.say(f"پرداخت انجام شد. جای {self.spot}. درب را باز کن و وارد شو")
        elif s == "parked":
            self.say(f"جای {self.spot} | زمان باقی‌مانده {left // 60:02d}:{left % 60:02d}")
        elif s == "exit":
            self.say("زمان تمام شد. درب را باز کن و خارج شو یا تمدید کن")


if __name__ == "__main__":
    ParkingApp().run()
