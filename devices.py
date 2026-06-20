"""
虚拟设备模块 —— 灯光、空调、风扇的纯内存模拟。
每个设备继承 QObject，状态变更通过 pyqtSignal 通知 UI。
"""

from PyQt5.QtCore import QObject, pyqtSignal


class LightDevice(QObject):
    """灯光设备 —— 支持开关、亮度(0-100)、颜色"""

    state_changed = pyqtSignal(dict)

    COLORS = ["warm_white", "cool_white", "red", "green", "blue", "yellow", "purple"]

    def __init__(self, device_id="light_1", name="客厅灯"):
        super().__init__()
        self.device_id = device_id
        self.name = name
        self._state = {"power": False, "brightness": 50, "color": "warm_white"}

    # ---- 只读状态 ----
    @property
    def state(self):
        return self._state.copy()

    # ---- 控制接口 ----
    def turn_on(self):
        if not self._state["power"]:
            self._state["power"] = True
            self.state_changed.emit(self.state)

    def turn_off(self):
        if self._state["power"]:
            self._state["power"] = False
            self.state_changed.emit(self.state)

    def toggle(self):
        if self._state["power"]:
            self.turn_off()
        else:
            self.turn_on()

    def set_brightness(self, value: int):
        v = max(0, min(100, int(value)))
        if self._state["brightness"] != v:
            self._state["brightness"] = v
            if v > 0 and not self._state["power"]:
                self._state["power"] = True
            self.state_changed.emit(self.state)

    def set_color(self, color: str):
        if color in self.COLORS and self._state["color"] != color:
            self._state["color"] = color
            self.state_changed.emit(self.state)


class ACDevice(QObject):
    """空调设备 —— 支持开关、温度(16-30)、模式、风速(1-3)"""

    state_changed = pyqtSignal(dict)

    MODES = ["cool", "heat", "fan", "auto"]
    MODE_LABELS = {"cool": "制冷", "heat": "制热", "fan": "送风", "auto": "自动"}

    def __init__(self, device_id="ac_1", name="卧室空调"):
        super().__init__()
        self.device_id = device_id
        self.name = name
        self._state = {"power": False, "temperature": 26, "mode": "cool", "fan_speed": 2}

    @property
    def state(self):
        return self._state.copy()

    # ---- 控制接口 ----
    def turn_on(self):
        if not self._state["power"]:
            self._state["power"] = True
            self.state_changed.emit(self.state)

    def turn_off(self):
        if self._state["power"]:
            self._state["power"] = False
            self.state_changed.emit(self.state)

    def set_temperature(self, value: int):
        v = max(16, min(30, int(value)))
        if self._state["temperature"] != v:
            self._state["temperature"] = v
            self.state_changed.emit(self.state)

    def increase_temperature(self):
        self.set_temperature(self._state["temperature"] + 1)

    def decrease_temperature(self):
        self.set_temperature(self._state["temperature"] - 1)

    def set_mode(self, mode: str):
        if mode in self.MODES and self._state["mode"] != mode:
            self._state["mode"] = mode
            self.state_changed.emit(self.state)

    def cycle_mode(self):
        idx = self.MODES.index(self._state["mode"])
        self.set_mode(self.MODES[(idx + 1) % len(self.MODES)])

    def set_fan_speed(self, speed: int):
        v = max(1, min(3, int(speed)))
        if self._state["fan_speed"] != v:
            self._state["fan_speed"] = v
            self.state_changed.emit(self.state)


class FanDevice(QObject):
    """风扇设备 —— 支持开关、风速(0-3)，风速 0 即关闭"""

    state_changed = pyqtSignal(dict)

    def __init__(self, device_id="fan_1", name="落地风扇"):
        super().__init__()
        self.device_id = device_id
        self.name = name
        self._state = {"power": False, "speed": 0}

    @property
    def state(self):
        return self._state.copy()

    # ---- 控制接口 ----
    def turn_on(self):
        if not self._state["power"]:
            self._state["power"] = True
            if self._state["speed"] == 0:
                self._state["speed"] = 1
            self.state_changed.emit(self.state)

    def turn_off(self):
        if self._state["power"] or self._state["speed"] > 0:
            self._state["power"] = False
            self._state["speed"] = 0
            self.state_changed.emit(self.state)

    def toggle(self):
        if self._state["power"]:
            self.turn_off()
        else:
            self.turn_on()

    def set_speed(self, speed: int):
        v = max(0, min(3, int(speed)))
        if self._state["speed"] != v:
            self._state["speed"] = v
            self._state["power"] = v > 0
            self.state_changed.emit(self.state)

    def cycle_speed(self):
        self.set_speed((self._state["speed"] + 1) % 4)


class DeviceManager:
    """Maintains smart-home device state and applies normalized agent actions."""

    def __init__(self, light: LightDevice, ac: ACDevice, fan: FanDevice):
        self.light = light
        self.ac = ac
        self.fan = fan

    def get_status(self):
        return {
            "light": self.light.state,
            "air_conditioner": self.ac.state,
            "fan": self.fan.state,
        }

    def format_status_reply(self):
        light = self.light.state
        ac = self.ac.state
        fan = self.fan.state
        return (
            f"当前设备状态：灯光{'开启' if light['power'] else '关闭'}，"
            f"亮度 {light['brightness']}%；"
            f"空调{'开启' if ac['power'] else '关闭'}，{ac['temperature']} 度；"
            f"风扇{'开启' if fan['power'] else '关闭'}，{fan['speed']} 档。"
        )

    def apply_action(self, action):
        device = action.get("device")
        command = action.get("action")
        value = action.get("value")

        if device == "light":
            if command == "on":
                self.light.turn_on()
            elif command == "off":
                self.light.turn_off()
        elif device == "fan":
            if command == "on":
                self.fan.turn_on()
            elif command == "off":
                self.fan.turn_off()
            elif command == "set_speed":
                self.fan.set_speed(value)
        elif device == "air_conditioner":
            if command == "on":
                self.ac.turn_on()
            elif command == "off":
                self.ac.turn_off()
            elif command == "set_temperature":
                self.ac.turn_on()
                self.ac.set_temperature(value)
            elif command == "set_speed":
                self.ac.set_fan_speed(value)
