#!/usr/bin/env python3
"""
AI-SmartHouse v3.2 — 小度式中文智能家居 Agent 中控 Demo。

产品化 PyQt5 Dashboard，集成唤醒词语音交互、TTS 回复、辅助式手势识别、
虚拟设备控制、场景模式、用户记忆和本地 fallback。
"""

import sys
import re
import platform
import subprocess
from datetime import datetime
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QSplitter,
    QTextEdit,
    QLineEdit,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QGridLayout,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import (
    QImage,
    QPixmap,
    QFont,
    QColor,
    QPalette,
    QLinearGradient,
    QBrush,
    QPainter,
    QTextCursor,
)

from devices import LightDevice, ACDevice, FanDevice, DeviceManager
from agent.action_schema import ActionExecutor
from agent.smart_home_agent import SmartHomeAgent
from speech_worker import SpeechWorker
from gesture_worker import GestureWorker

# ================================================================
# 跨平台字体 & 配色常量
# ================================================================

IS_MAC = platform.system() == "Darwin"


def _font(size=11):
    return QFont("PingFang SC" if IS_MAC else "Microsoft YaHei", size)


def _mono_font(size=10):
    return QFont("SF Mono" if IS_MAC else "Consolas", size)


# ================================================================
# 语音文本归一化与语义解析
# ================================================================

VOICE_TEXT_TRANSLATION = str.maketrans({
    "開": "开",
    "關": "关",
    "閉": "闭",
    "燈": "灯",
    "風": "风",
    "電": "电",
    "調": "调",
    "溫": "温",
    "聲": "声",
    "幫": "帮",
    "點": "点",
    "個": "个",
    "這": "这",
    "裡": "里",
    "嗎": "吗",
    "條": "调",
    "氣": "气",
    "熱": "热",
    "啟": "启",
    "製": "制",
})


def normalize_voice_text(text: str) -> str:
    """将 Whisper 可能输出的繁体文本归一化为简体，简体输入保持不变。"""
    return (text or "").translate(VOICE_TEXT_TRANSLATION).strip()


def parse_voice_intent(text: str):
    """基于归一化文本解析语音意图，返回 (action, label)。"""
    t = re.sub(r"\s+", "", text or "")

    light_keywords = ["灯", "灯光", "电灯", "等", "登"]
    fan_keywords = ["风扇", "电扇", "风"]
    ac_keywords = ["空调", "冷气", "制冷", "空条", "空调机"]

    on_keywords = ["打开一下", "开一下", "打开", "开启", "启动", "开"]
    off_keywords = ["关闭一下", "关一下", "关闭", "关掉", "停止", "关"]
    temp_up_keywords = ["温度高", "高一点", "加一度", "加一", "调高", "升高", "热一点"]
    temp_down_keywords = ["温度低", "低一点", "减一度", "减一", "调低", "降低", "冷一点"]
    light_up_keywords = ["灯亮一点", "灯光亮一点", "亮一点", "提高亮度", "亮度加一点", "灯调亮"]
    light_down_keywords = ["灯暗一点", "灯光暗一点", "暗一点", "降低亮度", "亮度减一点", "灯调暗"]
    light_color_keywords = ["换个颜色", "灯换颜色", "切换灯光颜色", "换成黄色", "换成白色", "换成蓝色", "换成红色", "换成绿色"]
    color_keywords = {
        "黄色": "yellow",
        "yellow": "yellow",
        "白色": "white",
        "white": "white",
        "蓝色": "blue",
        "blue": "blue",
        "红色": "red",
        "red": "red",
        "绿色": "green",
        "green": "green",
    }

    def has_any(keywords):
        return any(kw in t for kw in keywords)

    if has_any(light_up_keywords):
        return "light_brightness_up", "灯光亮度+10"
    if has_any(light_down_keywords):
        return "light_brightness_down", "灯光亮度-10"
    if has_any(light_color_keywords):
        for keyword, color in color_keywords.items():
            if keyword in t:
                return f"light_color:{color}", f"灯光颜色切换为{keyword}"
        return "light_color_cycle", "灯光颜色切换"

    if "回家模式" in t and any(kw in t for kw in ["开启", "启动", "回家模式"]):
        return "scene_home", "回家模式"
    if "睡眠模式" in t and any(kw in t for kw in ["开启", "启动", "睡眠模式"]):
        return "scene_sleep", "睡眠模式"

    # 先处理温度类自然语言，不要求一定出现“空调”。
    if has_any(temp_up_keywords):
        return "ac_temp_up", "空调温度+1"
    if has_any(temp_down_keywords):
        return "ac_temp_down", "空调温度-1"

    # 开关类优先处理关闭动作，避免“关闭一下灯”等句式被误判。
    if has_any(light_keywords):
        if has_any(off_keywords):
            return "light_off", "关闭灯光"
        if has_any(on_keywords):
            return "light_on", "打开灯光"

    if has_any(fan_keywords):
        if has_any(off_keywords):
            return "fan_off", "关闭风扇"
        if has_any(on_keywords):
            return "fan_on", "打开风扇"

    if has_any(ac_keywords):
        if has_any(off_keywords):
            return "ac_off", "关闭空调"
        if has_any(on_keywords):
            return "ac_on", "打开空调"

    return None, None


# 科技蓝配色
COLORS = {
    "bg_dark": "#080c1a",
    "bg_card": "#111633",
    "bg_card_alt": "#151d3d",
    "border": "#1e2d5a",
    "accent": "#00b4d8",
    "accent_light": "#48cae4",
    "accent_dim": "#0077b6",
    "green": "#10b981",
    "amber": "#f59e0b",
    "red": "#ef4444",
    "cyan": "#22d3ee",
    "blue": "#60a5fa",
    "text_primary": "#e8ecf4",
    "text_secondary": "#8892b0",
    "text_dim": "#5a6480",
    "header_gradient_start": "#0a1628",
    "header_gradient_end": "#111d3a",
    "camera_border": "#1a2f5a",
}

DARK_COLORS = COLORS.copy()
LIGHT_COLORS = {
    "bg_dark": "#F4F7FB",
    "bg_card": "#FFFFFF",
    "bg_card_alt": "#EEF2F7",
    "border": "#B9D7F5",
    "accent": "#007AFF",
    "accent_light": "#2F8CFF",
    "accent_dim": "#0A66C2",
    "green": "#16A34A",
    "amber": "#D97706",
    "red": "#DC2626",
    "cyan": "#0891B2",
    "blue": "#2563EB",
    "text_primary": "#172033",
    "text_secondary": "#526174",
    "text_dim": "#8A96A8",
    "header_gradient_start": "#FFFFFF",
    "header_gradient_end": "#EAF2FF",
    "camera_border": "#B9D7F5",
}


# ================================================================
# 摄像头画面组件
# ================================================================


class CameraWidget(QFrame):
    """带标题边框的摄像头画面组件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self.setObjectName("CameraCard")
        self.setMinimumSize(360, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # 标题栏
        title = QLabel("📷 实时视觉识别")
        title.setFont(_font(10))
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f"background: {COLORS['bg_card_alt']};"
            "padding: 6px 12px;"
            "border-radius: 6px;"
        )
        layout.addWidget(title)

        # 画面
        self._image_label = QLabel("摄像头启动中...")
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumSize(320, 240)
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image_label.setStyleSheet(
            f"QLabel {{"
            f"  background-color: {COLORS['bg_dark']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 6px;"
            f"  color: {COLORS['text_dim']};"
            f"  font-size: 13px;"
            f"}}"
        )
        layout.addWidget(self._image_label, 1)

    def update_frame(self, frame: np.ndarray):
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_BGR888)
        self._pixmap = QPixmap.fromImage(qimg)
        self._display_scaled()

    def _display_scaled(self):
        if self._pixmap and not self._pixmap.isNull():
            s = self._image_label.size()
            scaled = self._pixmap.scaled(s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._display_scaled()

    def clear(self):
        self._pixmap = None
        self._image_label.setText("摄像头未启动")
        self._image_label.setPixmap(QPixmap())


# ================================================================
# 状态指示器
# ================================================================


class StatusDot(QLabel):
    """彩色圆点 + 文字状态指示器"""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(f'<span style="color:{COLORS["text_secondary"]}">●</span> {text}')
        self.setFont(_font(10))
        self.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 2px 0px;")

    def set_ok(self, text):
        self.setText(f'<span style="color:{COLORS["green"]}">●</span> {text}')

    def set_warn(self, text):
        self.setText(f'<span style="color:{COLORS["amber"]}">●</span> {text}')

    def set_error(self, text):
        self.setText(f'<span style="color:{COLORS["red"]}">●</span> {text}')


# ================================================================
# 设备卡片
# ================================================================


class DeviceCard(QFrame):
    """单个设备的控制卡片"""

    def __init__(self, icon, name, parent=None):
        super().__init__(parent)
        self.setObjectName("DeviceCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(180)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(6)

        # 标题行：图标 + 名称
        header = QHBoxLayout()
        header.setSpacing(8)
        self._icon_label = QLabel(icon)
        self._icon_label.setFont(_font(30))
        header.addWidget(self._icon_label)

        name_label = QLabel(name)
        name_label.setFont(_font(14))
        name_label.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        header.addWidget(name_label)
        header.addStretch()
        self._layout.addLayout(header)

        # 状态行
        self._state_label = QLabel()
        self._state_label.setFont(_font(11))
        self._state_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self._state_label.setWordWrap(True)
        self._layout.addWidget(self._state_label)

        # 按钮行（子类填充）
        self._btn_layout = QHBoxLayout()
        self._btn_layout.setSpacing(6)
        self._layout.addLayout(self._btn_layout)

    def set_state_text(self, text):
        self._state_label.setText(text)

    def set_icon_text(self, text):
        self._icon_label.setText(text)

    def set_icon_color(self, color):
        self._icon_label.setStyleSheet(f"color: {color};")

    def set_visual_style(self, border_color=None, bg_color=None):
        border = border_color or COLORS["border"]
        bg = bg_color or COLORS["bg_card"]
        self.setStyleSheet(
            f"QFrame#DeviceCard {{"
            f"  background-color: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 12px;"
            f"}}"
        )

    def add_button(self, text, callback, accent=False):
        btn = QPushButton(text)
        btn.setFont(_font(10))
        btn.setFixedHeight(28)
        if accent:
            btn.setObjectName("AccentButton")
        btn.clicked.connect(callback)
        self._btn_layout.addWidget(btn)
        return btn


# ================================================================
# 语音控制区
# ================================================================


class SpeechCard(QFrame):
    """语音控制卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DeviceCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # 标题
        header = QHBoxLayout()
        header.setSpacing(8)
        icon = QLabel("🎤")
        icon.setFont(_font(18))
        header.addWidget(icon)

        title = QLabel("🎙️ 语音智能管家")
        title.setFont(_font(12))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # 状态
        self._status_label = QLabel("待命：请先说唤醒词")
        self._status_label.setFont(_font(10))
        self._status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # 按钮
        self._record_btn = QPushButton("开始监听")
        self._record_btn.setFont(_font(11))
        self._record_btn.setMinimumHeight(36)
        self._record_btn.setCheckable(True)
        self._record_btn.setEnabled(False)
        self._record_btn.setObjectName("AccentButton")
        layout.addWidget(self._record_btn)

        # 识别结果
        self._result_label = QLabel("唤醒词：小智小智 / 智能管家 / 你好管家")
        self._result_label.setFont(_font(10))
        self._result_label.setWordWrap(True)
        self._result_label.setStyleSheet(
            f"QLabel {{"
            f"  background-color: {COLORS['bg_card_alt']};"
            f"  border-radius: 6px;"
            f"  padding: 8px 10px;"
            f"  color: {COLORS['accent_light']};"
            f"}}"
        )
        layout.addWidget(self._result_label)

        self._tts_btn = QPushButton("语音回复：开启")
        self._tts_btn.setCheckable(True)
        self._tts_btn.setChecked(True)
        self._tts_btn.setObjectName("PillButton")
        layout.addWidget(self._tts_btn)

        hint = QLabel("说出唤醒词后，我会帮你控制设备、规划场景或回答问题。")
        hint.setFont(_font(8))
        hint.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px 0px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)


class AIAgentCard(QFrame):
    """AI natural-language interaction card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DeviceCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon = QLabel("AI")
        icon.setFont(_font(14))
        icon.setStyleSheet(f"color: {COLORS['accent_light']}; font-weight: bold;")
        header.addWidget(icon)

        title = QLabel("🧠 智能管家")
        title.setFont(_font(12))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入：我有点热 / 给我讲个笑话 / 查询设备状态")
        self.input.setMinimumHeight(34)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("AccentButton")
        self.send_btn.setMinimumHeight(34)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        self.reply = QTextEdit()
        self.reply.setReadOnly(True)
        self.reply.setFixedHeight(96)
        self.reply.setFont(_font(10))
        self.reply.setPlaceholderText("智能管家回复")
        layout.addWidget(self.reply)

        self.agent_log = QTextEdit()
        self.agent_log.setReadOnly(True)
        self.agent_log.setFixedHeight(150)
        self.agent_log.setFont(_mono_font(9))
        self.agent_log.setPlaceholderText("[用户]\n[大模型]\n[动作]\n[回复]")
        layout.addWidget(self.agent_log)


# ================================================================
# 底部日志区
# ================================================================


class LogPanel(QFrame):
    """Product dashboard log card."""

    def __init__(self, title="动作日志", parent=None):
        super().__init__(parent)
        self.setObjectName("LogPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 标题
        self._title = QLabel(title)
        self._title.setFont(_font(11))
        self._title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold; padding: 2px 6px;")
        layout.addWidget(self._title)

        # 日志文本区
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(_mono_font(9))
        self._text.setMinimumHeight(110)
        self._text.setMaximumHeight(170)
        self._text.setStyleSheet(
            f"QTextEdit {{"
            f"  background-color: {COLORS['bg_dark']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 6px;"
            f"  color: {COLORS['text_secondary']};"
            f"  padding: 6px 8px;"
            f"  selection-background-color: {COLORS['accent_dim']};"
            f"}}"
        )
        layout.addWidget(self._text)

    def apply_theme(self):
        self._text.setStyleSheet(
            f"QTextEdit {{"
            f"  background-color: {COLORS['bg_card_alt']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 6px;"
            f"  color: {COLORS['text_secondary']};"
            f"  padding: 6px 8px;"
            f"  selection-background-color: {COLORS['accent_dim']};"
            f"}}"
        )

    def append(self, message, level="info"):
        now = datetime.now().strftime("%H:%M:%S")
        level = level.lower()
        prefix_map = {
            "info": "INFO",
            "success": "INFO",
            "warn": "INFO",
            "voice": "VOICE",
            "speech": "VOICE",
            "gesture": "GESTURE",
            "device": "DEVICE",
            "scene": "SCENE",
            "error": "ERROR",
        }
        colors = {
            "info": COLORS["green"],
            "success": COLORS["green"],
            "warn": COLORS["green"],
            "error": COLORS["red"],
            "gesture": COLORS["amber"],
            "voice": COLORS["blue"],
            "speech": COLORS["blue"],
            "device": COLORS["cyan"],
            "scene": COLORS["amber"],
        }
        prefix = prefix_map.get(level, "INFO")
        c = colors.get(level, COLORS["text_secondary"])
        html = (
            f'<span style="color:{COLORS["text_dim"]}">[{now}]</span> '
            f'<span style="color:{c}">[{prefix}] {message}</span>'
        )
        self._text.append(html)
        # 自动滚动到底部
        self._text.moveCursor(QTextCursor.End)

    def append_plain(self, message):
        self._text.append(message)
        self._text.moveCursor(QTextCursor.End)


# ================================================================
# 主窗口
# ================================================================


class MainWindow(QMainWindow):
    """现代智能家居控制中心主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI-SmartHouse v3.2")
        self.setMinimumSize(1080, 720)

        # ---- 创建设备实例 ----
        self.light = LightDevice()
        self.ac = ACDevice()
        self.fan = FanDevice()
        self.device_manager = DeviceManager(self.light, self.ac, self.fan)
        self.agent = SmartHomeAgent(logger=self._on_llm_log)
        self.action_executor = ActionExecutor(self.device_manager)
        self._theme_name = "dark"

        # ---- 在主线程加载语音模型 ----
        whisper_model = self._load_whisper_model()

        # ---- 创建工作线程 ----
        self.speech_worker = SpeechWorker(whisper_model=whisper_model)
        self.gesture_worker = None
        self._gesture_recognition_active = False
        self._voice_mode = "wake"
        self._last_gesture_name = "无"
        self._active_scene = None

        # ---- 构建 UI ----
        self._setup_ui()

        # ---- 连接信号（业务逻辑不变） ----
        self._connect_signals()

        # ---- 全局样式 ----
        self._apply_global_style()

        # ---- 展示状态维护 ----
        self._gesture_idle_timer = QTimer(self)
        self._gesture_idle_timer.setInterval(1200)
        self._gesture_idle_timer.timeout.connect(self._reset_current_gesture)
        self._fan_anim_index = 0
        self._fan_anim_frames = ["🌀", "◐", "◓", "◑", "◒"]
        self._fan_anim_timer = QTimer(self)
        self._fan_anim_timer.setInterval(160)
        self._fan_anim_timer.timeout.connect(self._animate_fan_icon)
        self._update_light_visual()
        self._update_fan_visual(log_change=False)
        self._update_ac_visual()

        # ---- 启动工作线程 ----
        self._show_startup_logs()
        self.speech_worker.start()
        self._log("系统启动成功", "info")
        QTimer.singleShot(200, self._detect_llm_status)

    # ================================================================
    # 模型加载（业务逻辑不变）
    # ================================================================

    def _load_whisper_model(self):
        try:
            from faster_whisper import WhisperModel
            self._log("正在加载语音识别模型...", "info")
            model = WhisperModel("base", device="cpu", compute_type="int8", num_workers=2)
            return model
        except Exception as e:
            print(f"[ERROR] Whisper model load failed: {e}")
            return None

    # ================================================================
    # 日志快捷方法
    # ================================================================

    def _log(self, msg, level="info"):
        if level == "gesture" and hasattr(self, "gesture_log_panel"):
            self.gesture_log_panel.append(msg, level)
        elif hasattr(self, "log_panel"):
            self.log_panel.append(msg, level)

    def _show_startup_logs(self):
        messages = [
            "系统初始化中...",
            "摄像头模块待命",
            "手势识别待命",
            "语音唤醒模块加载完成",
            "设备控制模块加载完成",
        ]
        for message in messages:
            self._log(message, "info")

    def _toggle_theme(self):
        self._theme_name = "light" if self._theme_name == "dark" else "dark"
        self._apply_theme()
        self._log("浅色科技主题已启用" if self._theme_name == "light" else "深色科技主题已启用", "info")

    def _apply_theme(self):
        COLORS.clear()
        COLORS.update(LIGHT_COLORS if self._theme_name == "light" else DARK_COLORS)
        if hasattr(self, "_theme_btn"):
            self._theme_btn.setText("深色主题" if self._theme_name == "light" else "浅色主题")
        self._apply_global_style()
        if hasattr(self, "log_panel"):
            self.log_panel.apply_theme()
        self._update_light_visual()
        self._update_fan_visual(log_change=False)
        self._update_ac_visual()

    # ================================================================
    # UI 构建
    # ================================================================

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(14)

        root.addWidget(self._create_header())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._create_sidebar())
        body.addWidget(self._create_dashboard_panel(), 1)
        root.addLayout(body, 1)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

    def _create_header(self):
        """顶部标题栏"""
        header = QFrame()
        header.setObjectName("HeaderBar")
        header.setFixedHeight(86)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 10, 22, 10)
        layout.setSpacing(16)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        main_title = QLabel("AI-SmartHouse")
        main_title.setFont(_font(20))
        main_title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")

        sub_title = QLabel("大模型驱动的智能家居中控系统")
        sub_title.setFont(_font(9))
        sub_title.setStyleSheet(f"color: {COLORS['accent_light']};")

        title_layout.addWidget(main_title)
        title_layout.addWidget(sub_title)
        layout.addLayout(title_layout)
        layout.addStretch()

        self._header_time = QLabel("--:--")
        self._header_time.setFont(_mono_font(12))
        self._header_time.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self._header_time)

        self._status_sys = StatusDot("系统：运行中")
        self._status_llm = StatusDot("大模型状态：检测中")
        self._status_speech = StatusDot("语音状态：待命")
        self._status_cam = StatusDot("摄像头：未连接")
        self._status_gesture = StatusDot("手势状态：待命")
        self._status_control = StatusDot("控制状态：待命")
        for status in (self._status_llm, self._status_speech, self._status_cam):
            layout.addWidget(status)
        self._status_sys.set_ok("系统：运行中")
        self._status_speech.set_ok("语音状态：待命")
        self._status_cam.set_warn("摄像头：未连接")
        self._status_gesture.set_ok("手势状态：待命")
        self._status_control.set_ok("控制状态：待命")
        self._status_llm.set_warn("大模型状态：检测中")

        self._theme_btn = QPushButton("浅色主题")
        self._theme_btn.setFont(_font(9))
        self._theme_btn.setFixedHeight(30)
        self._theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self._theme_btn)

        version = QLabel("v3.2")
        version.setFont(_font(8))
        version.setStyleSheet(f"color: {COLORS['text_dim']};")
        layout.addWidget(version)

        return header

    def _update_clock(self):
        now = datetime.now()
        if hasattr(self, "_header_time"):
            self._header_time.setText(now.strftime("%H:%M"))
        if hasattr(self, "_hero_time"):
            self._hero_time.setText(now.strftime("%H:%M"))
            weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            self._hero_date.setText(f"{now.month}月{now.day}日 {weekdays[now.weekday()]}")
            hour = now.hour
            if hour < 12:
                greeting = "上午好"
                suggestion = "适合开启学习模式，保持明亮和安静。"
            elif hour < 18:
                greeting = "下午好"
                suggestion = "适合学习，已为你保持安静环境。"
            else:
                greeting = "晚上好"
                suggestion = "夜间建议休息，可一键启用睡眠模式。"
            self._hero_greeting.setText(greeting)
            self._hero_suggestion.setText(suggestion)

    def _set_home_mode(self, text):
        if hasattr(self, "_home_mode_label"):
            self._home_mode_label.setText(f"当前模式：{text}")

    def _create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(12)

        home_title = QLabel("我的智能宿舍")
        home_title.setFont(_font(14))
        home_title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(home_title)

        self._home_mode_label = QLabel("当前模式：待命")
        self._home_mode_label.setFont(_font(10))
        self._home_mode_label.setStyleSheet(f"color: {COLORS['accent_light']}; padding-bottom: 8px;")
        layout.addWidget(self._home_mode_label)

        status_title = QLabel("今日状态")
        status_title.setFont(_font(11))
        status_title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(status_title)

        self._home_llm_label = StatusDot("大模型检测中")
        self._home_voice_label = StatusDot("语音待命")
        self._home_camera_label = StatusDot("摄像头待命")
        self._home_device_label = StatusDot("设备数：3")
        self._home_voice_label.set_ok("语音待命")
        self._home_camera_label.set_warn("摄像头待命")
        self._home_device_label.set_ok("设备数：3")
        for label in (self._home_llm_label, self._home_voice_label, self._home_camera_label, self._home_device_label):
            layout.addWidget(label)

        layout.addStretch()
        hint = QLabel("AI-SmartHouse v3.2\nBUPT · AI Agent Demo")
        hint.setWordWrap(True)
        hint.setFont(_font(9))
        hint.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 8px;")
        layout.addWidget(hint)
        return sidebar

    def _create_dashboard_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 0, 6, 0)
        layout.setSpacing(14)

        main_col = QVBoxLayout()
        main_col.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._create_clock_card(), 3)
        self.speech_card = SpeechCard()
        top_row.addWidget(self.speech_card, 2)
        main_col.addLayout(top_row)

        device_grid = QGridLayout()
        device_grid.setSpacing(14)
        device_grid.addWidget(self._create_light_card(), 0, 0)
        device_grid.addWidget(self._create_fan_card(), 0, 1)
        device_grid.addWidget(self._create_ac_card(), 0, 2)
        main_col.addLayout(device_grid)

        main_col.addWidget(self._create_scene_section())
        self.ai_card = AIAgentCard()
        main_col.addWidget(self.ai_card)

        log_grid = QGridLayout()
        log_grid.setSpacing(14)
        self.log_panel = LogPanel("动作日志")
        log_grid.addWidget(self.log_panel, 0, 0, 1, 2)
        log_grid.addWidget(self._create_aux_interaction_card(), 0, 2)
        main_col.addLayout(log_grid)
        layout.addLayout(main_col)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _create_clock_card(self):
        frame = QFrame()
        frame.setObjectName("HeroCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        self._hero_greeting = QLabel("下午好")
        self._hero_greeting.setFont(_font(18))
        self._hero_greeting.setStyleSheet(f"color: {COLORS['accent_light']}; font-weight: bold;")
        self._hero_time = QLabel("--:--")
        self._hero_time.setFont(_font(60))
        self._hero_time.setStyleSheet(f"color: #ffffff; font-weight: bold;")
        self._hero_date = QLabel("6月12日 星期五")
        self._hero_date.setFont(_font(14))
        self._hero_date.setStyleSheet(f"color: {COLORS['cyan']};")
        self._hero_suggestion = QLabel("适合学习，已为你保持安静环境")
        self._hero_suggestion.setFont(_font(12))
        self._hero_suggestion.setWordWrap(True)
        self._hero_suggestion.setStyleSheet(f"color: {COLORS['text_secondary']}; padding-top: 10px;")

        layout.addWidget(self._hero_greeting)
        layout.addWidget(self._hero_time)
        layout.addWidget(self._hero_date)
        layout.addWidget(self._hero_suggestion)
        return frame

    def _create_aux_interaction_card(self):
        frame = QFrame()
        frame.setObjectName("DeviceCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("✋ 辅助交互")
        title.setFont(_font(12))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(title)

        self.gesture_label = QLabel("手势状态：待命")
        self.gesture_label.setFont(_font(10))
        self.gesture_label.setStyleSheet(f"color: {COLORS['accent_light']}; font-weight: bold;")
        layout.addWidget(self.gesture_label)

        self._gesture_recent_label = QLabel("最近识别：无")
        self._gesture_recent_label.setFont(_font(9))
        self._gesture_recent_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self._gesture_recent_label)

        self.camera_widget = CameraWidget()
        self.camera_widget.setMaximumHeight(160)
        self.camera_widget.clear()
        self.camera_widget.setVisible(False)
        layout.addWidget(self.camera_widget)

        self._gesture_btn = QPushButton("开始一次手势识别")
        self._gesture_btn.setObjectName("AccentButton")
        self._gesture_btn.setMinimumHeight(36)
        layout.addWidget(self._gesture_btn)

        self.gesture_log_panel = LogPanel("手势日志")
        self.gesture_log_panel.setMaximumHeight(150)
        layout.addWidget(self.gesture_log_panel)
        return frame

    def _create_quick_commands_section(self):
        frame = QFrame()
        frame.setObjectName("DeviceCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("辅助指令")
        title.setFont(_font(12))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        for text in ["我有点热", "我要睡觉了", "开启学习模式", "查询设备状态"]:
            btn = QPushButton(text)
            btn.setObjectName("PillButton")
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _checked=False, t=text: self._handle_agent_text(t))
            row.addWidget(btn)
        layout.addLayout(row)
        return frame

    def _create_left_panel(self):
        """左侧面板：摄像头 + 手势信息"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 摄像头
        self.camera_widget = CameraWidget()
        layout.addWidget(self.camera_widget, 1)

        # 手势识别结果
        gesture_frame = QFrame()
        gesture_frame.setObjectName("DeviceCard")
        g_layout = QHBoxLayout(gesture_frame)
        g_layout.setContentsMargins(14, 10, 14, 10)

        gesture_icon = QLabel("✋")
        gesture_icon.setFont(_font(16))
        g_layout.addWidget(gesture_icon)

        self.gesture_label = QLabel("等待手势识别...")
        self.gesture_label.setFont(_font(12))
        self.gesture_label.setStyleSheet(
            f"color: {COLORS['accent_light']}; font-weight: bold;"
        )
        g_layout.addWidget(self.gesture_label)
        g_layout.addStretch()

        layout.addWidget(gesture_frame)

        return panel

    def _create_right_panel(self):
        """右侧面板：滚动区域包含状态 + 设备卡片 + 语音控制"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}"
            f"QScrollBar:vertical {{ width: 4px; background: {COLORS['bg_dark']}; }}"
            f"QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 2px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        # ---- 系统状态 ----
        layout.addWidget(self._create_status_section())

        # ---- 智能场景 ----
        layout.addWidget(self._create_scene_section())

        # ---- 设备卡片 ----
        layout.addWidget(self._create_light_card())
        layout.addWidget(self._create_ac_card())
        layout.addWidget(self._create_fan_card())

        # ---- 语音控制 ----
        self.speech_card = SpeechCard()
        layout.addWidget(self.speech_card)

        # ---- AI Agent ----
        self.ai_card = AIAgentCard()
        layout.addWidget(self.ai_card)

        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _create_status_section(self):
        """系统状态指示区"""
        frame = QFrame()
        frame.setObjectName("DeviceCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        title = QLabel("📊 系统状态")
        title.setFont(_font(11))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(title)

        self._status_sys = StatusDot("系统状态：待机")
        self._status_cam = StatusDot("摄像头状态：未连接")
        self._status_speech = StatusDot("语音状态：待命")
        self._status_gesture = StatusDot("当前手势：无")
        self._status_control = StatusDot("控制模式：待机")
        self._status_llm = StatusDot("大模型状态：检测中")

        self._status_sys.set_ok("系统状态：运行中")
        self._status_speech.set_ok("语音状态：待命")
        self._status_gesture.set_ok("当前手势：无")
        self._status_control.set_ok("控制模式：待机")
        self._status_llm.set_warn("大模型状态：检测中")
        layout.addWidget(self._status_sys)
        layout.addWidget(self._status_cam)
        layout.addWidget(self._status_speech)
        layout.addWidget(self._status_gesture)
        layout.addWidget(self._status_control)
        layout.addWidget(self._status_llm)

        return frame

    def _create_scene_section(self):
        """Product scene cards."""
        frame = QFrame()
        frame.setObjectName("DeviceCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        title = QLabel("场景")
        title.setFont(_font(12))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(12)
        scenes = [
            ("🏠 回家", "打开灯光，空调调至 26 度，关闭风扇", self._activate_home_mode),
            ("🌙 睡眠", "关灯、关闭风扇，空调调整为偏好温度", self._activate_sleep_mode),
            ("📚 学习", "打开灯光，关闭风扇，空调保持舒适温度", self._activate_study_mode),
            ("🌱 节能", "降低能耗，关闭风扇并设置节能温度", self._activate_energy_mode),
        ]
        for index, (name, desc, callback) in enumerate(scenes):
            grid.addWidget(self._create_scene_card(name, desc, callback), index // 2, index % 2)
        layout.addLayout(grid)

        return frame

    def _create_scene_card(self, name, description, callback):
        card = QFrame()
        card.setObjectName("SceneCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title = QLabel(name)
        title.setFont(_font(11))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        desc = QLabel(description)
        desc.setFont(_font(8))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']};")
        btn = QPushButton("启用")
        btn.setObjectName("PillButton")
        btn.setMinimumHeight(30)
        btn.clicked.connect(callback)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(btn)
        return card

    def _create_demo_help_section(self):
        """Legacy help card kept for compatibility with older layouts."""
        frame = QFrame()
        frame.setObjectName("DeviceCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        title = QLabel("Interaction Guide")
        title.setFont(_font(11))
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(title)

        help_text = QLabel(
            "手势说明：\n"
            "OK：唤醒控制模式\n"
            "手掌：灯光开关\n"
            "握拳：风扇开关\n"
            "点赞：空调温度+1\n"
            "倒赞：空调温度-1\n"
            "V字：空调开关\n\n"
            "语音说明：\n"
            "支持“打开灯”“关闭灯”“打开风扇”“关闭风扇”“打开空调”“关闭空调”等指令"
        )
        help_text.setFont(_font(9))
        help_text.setWordWrap(True)
        help_text.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(help_text)

        return frame

    # ---- 设备卡片工厂方法 ----

    def _create_light_card(self):
        card = DeviceCard("💡", "灯光")
        card.set_state_text(self._light_state_text())
        card.add_button("开关", self.light.toggle)
        card.add_button("亮度+", lambda: self.light.set_brightness(self.light.state["brightness"] + 10))
        card.add_button("亮度-", lambda: self.light.set_brightness(self.light.state["brightness"] - 10))
        card.add_button("换色", self._cycle_light_color)
        self._light_card = card
        return card

    def _create_ac_card(self):
        card = DeviceCard("❄️", "空调")
        card.set_state_text(self._ac_state_text())
        card.add_button("开关", self._toggle_ac)
        card.add_button("升温", self.ac.increase_temperature)
        card.add_button("降温", self.ac.decrease_temperature)
        card.add_button("模式", self.ac.cycle_mode)
        self._ac_card = card
        return card

    def _create_fan_card(self):
        card = DeviceCard("🌀", "风扇")
        card.set_state_text(self._fan_state_text())
        card.add_button("开关", self.fan.toggle)
        card.add_button("风速", self.fan.cycle_speed)
        self._fan_card = card
        return card

    # ---- 设备状态文本 ----

    def _light_state_text(self):
        s = self.light.state
        pwr = "开启" if s["power"] else "关闭"
        return f"状态：{pwr}\n亮度：{s['brightness']}%  ·  色彩：{s['color']}"

    def _ac_state_text(self):
        s = self.ac.state
        pwr = "开启" if s["power"] else "关闭"
        mode = ACDevice.MODE_LABELS.get(s["mode"], s["mode"])
        return f"状态：{pwr}\n温度：{s['temperature']}℃  ·  {mode}"

    def _fan_state_text(self):
        s = self.fan.state
        pwr = "开启" if s["power"] else "关闭"
        return f"状态：{pwr}\n风速：{s['speed']} 档"

    # ---- 辅助操作 ----

    def _toggle_ac(self):
        if self.ac.state["power"]:
            self.ac.turn_off()
        else:
            self.ac.turn_on()

    def _cycle_light_color(self):
        colors = ["yellow", "cool_white", "blue", "red", "green", "purple"]
        cur = self.light.state["color"]
        idx = colors.index(cur) if cur in colors else -1
        self.light.set_color(colors[(idx + 1) % len(colors)])

    def _set_light_color_from_voice(self, color: str):
        color_map = {
            "yellow": "yellow",
            "white": "cool_white",
            "blue": "blue",
            "red": "red",
            "green": "green",
        }
        target = color_map.get(color)
        if target:
            self.light.set_color(target)
            if not self.light.state["power"]:
                self.light.turn_on()

    def _activate_home_mode(self):
        self._active_scene = "home"
        self._set_home_mode("回家模式")
        self.light.turn_on()
        self.light.set_brightness(80)
        self.light.set_color("yellow")
        self.ac.turn_on()
        self.ac.set_temperature(26)
        self.fan.turn_off()
        self._log("回家模式已启动", "scene")

    def _activate_sleep_mode(self):
        self._active_scene = "sleep"
        self._set_home_mode("睡眠模式")
        self.light.turn_off()
        self.ac.turn_on()
        self.ac.set_temperature(self.agent.memory.get_sleep_temperature(26))
        self.fan.turn_off()
        self._log("睡眠模式已启动", "scene")

    def _activate_study_mode(self):
        self._active_scene = "study"
        self._set_home_mode("学习模式")
        self.light.turn_on()
        self.light.set_brightness(90)
        self.light.set_color("cool_white")
        self.ac.turn_on()
        self.ac.set_temperature(26)
        self.fan.turn_off()
        self._log("学习模式已启动", "scene")

    def _activate_energy_mode(self):
        self._active_scene = "eco"
        self._set_home_mode("节能模式")
        self.light.set_brightness(35)
        self.ac.turn_on()
        self.ac.set_temperature(27)
        self.fan.turn_off()
        self._log("节能模式已启动", "scene")

    def _light_color_hex(self, color_name):
        return {
            "warm_white": "#facc15",
            "cool_white": "#f8fafc",
            "white": "#f8fafc",
            "yellow": "#facc15",
            "red": "#ef4444",
            "green": "#22c55e",
            "blue": "#3b82f6",
            "purple": "#a855f7",
        }.get(color_name, COLORS["amber"])

    def _update_light_visual(self):
        state = self.light.state
        if not hasattr(self, "_light_card"):
            return

        if not state["power"]:
            self._light_card.set_icon_color(COLORS["text_dim"])
            self._light_card._state_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
            self._light_card.set_visual_style(COLORS["border"], COLORS["bg_card"])
            return

        color = self._light_color_hex(state["color"])
        brightness = max(0, min(100, state["brightness"]))
        alpha = 0.16 + brightness / 100 * 0.22
        bg = f"rgba(17, 22, 51, {1 - alpha:.2f})"
        self._light_card.set_icon_color(color)
        self._light_card._state_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._light_card.set_visual_style(color, bg)

    def _update_fan_visual(self, log_change=True):
        if not hasattr(self, "_fan_card"):
            return

        if self.fan.state["power"]:
            fan_color = COLORS["green"] if self._active_scene == "sleep" else COLORS["cyan"]
            self._fan_card.set_icon_color(fan_color)
            self._fan_card._state_label.setStyleSheet(f"color: {fan_color}; font-weight: bold;")
            self._fan_card.set_visual_style(fan_color, COLORS["bg_card"])
            if not self._fan_anim_timer.isActive():
                self._fan_anim_timer.start()
                if log_change:
                    self._log("风扇已开启，动画启动", "device")
        else:
            was_active = self._fan_anim_timer.isActive()
            self._fan_anim_timer.stop()
            self._fan_card.set_icon_text("🌀")
            self._fan_card.set_icon_color(COLORS["text_dim"])
            self._fan_card._state_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
            self._fan_card.set_visual_style(COLORS["border"], COLORS["bg_card"])
            if log_change and was_active:
                self._log("风扇已关闭，动画停止", "device")

    def _animate_fan_icon(self):
        if not self.fan.state["power"] or not hasattr(self, "_fan_card"):
            return
        self._fan_anim_index = (self._fan_anim_index + 1) % len(self._fan_anim_frames)
        self._fan_card.set_icon_text(self._fan_anim_frames[self._fan_anim_index])

    def _update_ac_visual(self):
        if not hasattr(self, "_ac_card"):
            return

        if self.ac.state["power"]:
            self._ac_card.set_icon_color(COLORS["blue"])
            self._ac_card._state_label.setStyleSheet(f"color: {COLORS['blue']}; font-weight: bold;")
            self._ac_card.set_visual_style(COLORS["blue"], COLORS["bg_card"])
        else:
            self._ac_card.set_icon_color(COLORS["text_dim"])
            self._ac_card._state_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
            self._ac_card.set_visual_style(COLORS["border"], COLORS["bg_card"])

    # ================================================================
    # 信号连接（业务逻辑不变）
    # ================================================================

    def _connect_signals(self):
        # ---- 设备信号 ----
        self.light.state_changed.connect(self._on_light_changed)
        self.ac.state_changed.connect(self._on_ac_changed)
        self.fan.state_changed.connect(self._on_fan_changed)

        # ---- 语音线程 ----
        self.speech_worker.status_changed.connect(self._on_speech_status)
        self.speech_worker.transcription_ready.connect(self._on_transcription)
        self.speech_worker.error_occurred.connect(self._on_error)

        # ---- 语音按钮 ----
        self.speech_card._record_btn.clicked.connect(self._on_record_clicked)
        self.speech_card._tts_btn.clicked.connect(self._on_tts_toggled)

        # ---- AI Agent 输入 ----
        self.ai_card.send_btn.clicked.connect(self._on_ai_send)
        self.ai_card.input.returnPressed.connect(self._on_ai_send)
        self._gesture_btn.clicked.connect(self._start_gesture_recognition)

    def _connect_gesture_worker(self):
        self.gesture_worker.frame_ready.connect(self._on_frame_ready)
        self.gesture_worker.gesture_detected.connect(self._on_gesture)
        self.gesture_worker.command_triggered.connect(self._on_gesture_command)
        self.gesture_worker.status_changed.connect(self._on_gesture_status)
        self.gesture_worker.error_occurred.connect(self._on_error)

    # ---- 设备状态更新 ----

    def _on_light_changed(self, state):
        self._light_card.set_state_text(self._light_state_text())
        self._update_light_visual()
        pwr = "开启" if state["power"] else "关闭"
        self._log(f"灯光 → {pwr}（亮度 {state['brightness']}%）", "device")

    def _on_ac_changed(self, state):
        self._ac_card.set_state_text(self._ac_state_text())
        self._update_ac_visual()
        pwr = "开启" if state["power"] else "关闭"
        mode = ACDevice.MODE_LABELS.get(state["mode"], state["mode"])
        self._log(f"空调 → {pwr}（{state['temperature']}°C {mode}）", "device")

    def _on_fan_changed(self, state):
        self._fan_card.set_state_text(self._fan_state_text())
        self._update_fan_visual()
        pwr = "开启" if state["power"] else "关闭"
        self._log(f"风扇 → {pwr}（速度 {state['speed']} 档）", "device")

    # ---- 手势处理 ----

    def _start_gesture_recognition(self):
        if self._gesture_recognition_active:
            return
        self._gesture_recognition_active = True
        self._status_gesture.set_warn("手势状态：识别中")
        self.gesture_label.setText("手势状态：识别中")
        self._gesture_btn.setEnabled(False)
        self._gesture_btn.setText("识别中...")
        if hasattr(self, "camera_widget"):
            self.camera_widget.setVisible(True)
        self.gesture_worker = GestureWorker()
        self._connect_gesture_worker()
        self.gesture_worker.start()
        self._log("手势识别已启动，等待一个有效手势", "gesture")

    def _stop_gesture_recognition(self, label="已识别"):
        self._gesture_recognition_active = False
        self._status_gesture.set_ok(f"手势状态：{label}")
        self.gesture_label.setText(f"手势状态：{label}")
        self._gesture_btn.setEnabled(True)
        self._gesture_btn.setText("开始一次手势识别")
        if hasattr(self, "camera_widget"):
            self.camera_widget.setVisible(False)
        if self.gesture_worker:
            self.gesture_worker.stop()
            self.gesture_worker.wait(1500)
            self.gesture_worker = None

    def _execute_single_gesture(self, display_name):
        mapping = {
            "手掌": ("灯光开关", self.light.toggle),
            "握拳": ("风扇开关", self.fan.toggle),
            "点赞": ("空调升温", self.ac.increase_temperature),
            "倒赞": ("空调降温", self.ac.decrease_temperature),
            "V字": ("空调开关", self._toggle_ac),
        }
        item = mapping.get(display_name)
        if not item:
            return False
        action_label, callback = item
        callback()
        if hasattr(self, "_gesture_recent_label"):
            self._gesture_recent_label.setText(f"最近识别：{display_name}")
        self._log(f"识别结果：{display_name} → {action_label}", "gesture")
        return True

    def _on_frame_ready(self, frame):
        self.camera_widget.update_frame(frame)
        self._status_cam.set_ok("摄像头：已连接")
        if hasattr(self, "_home_camera_label"):
            self._home_camera_label.set_ok("摄像头识别中")

    def _on_gesture(self, gesture_name: str, confidence: float):
        display_name = self._normalize_gesture_name(gesture_name)
        if not self._gesture_recognition_active:
            return
        self.gesture_label.setText(f"识别结果：{display_name} {confidence:.0%}")
        if self._execute_single_gesture(display_name):
            self._stop_gesture_recognition("已识别")

    def _on_gesture_ignored(self, gesture_name: str):
        return

    def _on_gesture_status(self, status: str):
        # 更新手势区域标签（显示状态机状态）
        self.gesture_label.setText(status)

        if "摄像头" in status and "运行中" in status:
            self._status_cam.set_ok("摄像头：已连接")
            self._status_control.set_ok("控制状态：待命")
        elif "控制模式已激活" in status:
            self._status_control.set_ok("控制状态：识别中")
        elif "唤醒确认" in status or "检测到唤醒手势" in status:
            self._status_control.set_warn("控制状态：识别中")
        elif "唤醒取消" in status:
            self._status_control.set_ok("控制状态：待命")
        elif "命令已执行" in status:
            self._status_control.set_warn("控制状态：冷却")
        elif "冷却" in status:
            self._status_control.set_warn("控制状态：冷却")
        elif "超时" in status:
            self._status_control.set_ok("控制状态：待命")
        elif "不可用" in status or "失败" in status:
            self._status_cam.set_error("摄像头：离线")
            self._status_control.set_ok("控制状态：待命")
            self._stop_gesture_recognition("待命")
        elif "加载" in status:
            self._status_control.set_ok("控制状态：待命")

    # ---- 语音处理 ----

    def _on_speech_status(self, status: str):
        self.speech_card._status_label.setText(status)

        if "就绪" in status and not self.speech_card._record_btn.isEnabled():
            self.speech_card._record_btn.setEnabled(True)
            self._status_speech.set_ok("语音状态：待命")
            if hasattr(self, "_home_voice_label"):
                self._home_voice_label.set_ok("语音待命")
            self._log("语音唤醒模式待命", "voice")

        if "正在录音" in status or "正在监听" in status:
            self._status_speech.set_warn("语音状态：监听中")
            if hasattr(self, "_home_voice_label"):
                self._home_voice_label.set_warn("正在聆听")
        elif "正在识别" in status:
            self._status_speech.set_warn("语音状态：识别中")
            if hasattr(self, "_home_voice_label"):
                self._home_voice_label.set_warn("语音处理中")
        elif any(kw in status for kw in ["识别完成", "未识别", "重试"]):
            self._status_speech.set_ok("语音状态：待命")
            if hasattr(self, "_home_voice_label"):
                self._home_voice_label.set_ok("语音待命")
        elif "失败" in status or "崩溃" in status:
            self._status_speech.set_error("语音状态：异常")
            if hasattr(self, "_home_voice_label"):
                self._home_voice_label.set_error("语音异常")

        if any(kw in status for kw in ["识别完成", "未识别", "失败", "重试"]):
            if self.speech_card._record_btn.isChecked():
                self.speech_card._record_btn.setChecked(False)
                self.speech_card._record_btn.setText("开始监听")

    def _on_transcription(self, text: str):
        self.speech_card._result_label.setText(f"📝 {text}")
        normalized = normalize_voice_text(text)
        wake_words = ["小智小智", "智能管家", "你好管家"]
        compact = normalized.replace(" ", "")
        if self._voice_mode == "wake":
            if any(word in compact for word in wake_words):
                self._voice_mode = "command"
                self.speech_card._status_label.setText("我在，请说。")
                self.speech_card._result_label.setText("我在，请说。")
                self._status_speech.set_warn("语音状态：等待命令")
                self._log("已检测到唤醒词，进入命令识别模式", "voice")
                self._speak("我在，请说。")
            else:
                self.speech_card._status_label.setText("未检测到唤醒词，请说：小智小智")
                self._log(f"未触发唤醒词：{normalized}", "voice")
            return

        self._voice_mode = "wake"
        self._handle_agent_text(normalized)

    def _on_error(self, msg: str):
        if "摄像头" in msg:
            self._status_cam.set_error("摄像头：离线")
        elif "语音" in msg or "麦克风" in msg or "PyAudio" in msg:
            self._status_speech.set_error("语音状态：异常")
            if hasattr(self, "_home_voice_label"):
                self._home_voice_label.set_error("语音异常")
        self._log(f"异常信息: {msg}", "error")

    # ---- 录音按钮 ----

    def _on_record_clicked(self, checked: bool):
        if checked:
            self.speech_card._record_btn.setText("停止监听")
            self._status_speech.set_warn("语音状态：监听中")
            self.speech_worker.start_recording()
        else:
            self.speech_card._record_btn.setText("开始监听")
            self._status_speech.set_warn("语音状态：识别中")
            self.speech_worker.stop_recording()

    def _on_tts_toggled(self, checked):
        self.speech_card._tts_btn.setText("语音回复：开启" if checked else "语音回复：关闭")

    def _speak(self, text):
        if not getattr(self.speech_card, "_tts_btn", None) or not self.speech_card._tts_btn.isChecked():
            return
        try:
            if platform.system() == "Darwin":
                subprocess.run(["say", text], timeout=12, check=False)
        except Exception:
            pass

    def _on_ai_send(self):
        text = self.ai_card.input.text().strip()
        if not text:
            return
        self.ai_card.input.clear()
        self._handle_agent_text(text)

    def _append_agent_log(self, message):
        self.ai_card.agent_log.append(message)
        self.ai_card.agent_log.moveCursor(QTextCursor.End)

    def _on_llm_log(self, message):
        if message.startswith("[LLM ERROR]"):
            self._set_llm_fallback()
            self._log(message, "error")
        else:
            if message.startswith("[LLM] Response:"):
                self._set_llm_online()
            self._log(message, "voice")

    def _detect_llm_status(self):
        self._set_llm_fallback("检测中")
        ok, detail = self.agent.llm_client.check_online()
        if ok:
            self._set_llm_online()
            self._log(f"[LLM] Startup check OK: {detail}", "voice")
        else:
            self._set_llm_fallback()
            self._log(f"[LLM ERROR] Startup check failed: {detail}", "error")

    def _set_llm_online(self):
        if hasattr(self, "_status_llm"):
            self._status_llm.set_ok("大模型状态：DeepSeek 在线")
        if hasattr(self, "_home_llm_label"):
            self._home_llm_label.set_ok("大模型在线")

    def _set_llm_fallback(self, suffix=None):
        text = "大模型状态：本地规则模式"
        if suffix:
            text = f"大模型状态：{suffix}"
        if hasattr(self, "_status_llm"):
            self._status_llm.set_warn(text)
        if hasattr(self, "_home_llm_label"):
            self._home_llm_label.set_warn("本地规则模式")

    def _handle_agent_text(self, text: str):
        raw_text = text.strip()
        normalized_text = normalize_voice_text(raw_text)
        if "手势识别" in normalized_text and any(keyword in normalized_text for keyword in ["开始", "开启", "进入"]):
            self._start_gesture_recognition()
            reply = "已进入手势识别模式，请做一个手势。"
            self.ai_card.reply.setText(reply)
            self._append_agent_log(f"[用户] {normalized_text}")
            self._append_agent_log("[回复]")
            self._append_agent_log(reply)
            self._speak(reply)
            return
        self._log(f"[USER] {normalized_text}", "voice")
        self._append_agent_log(f"[用户] {normalized_text}")

        result = self.agent.plan(normalized_text, self.device_manager.get_status())
        execution = self.action_executor.execute(result)
        reply = execution["reply"]

        self.ai_card.reply.setText(reply)
        self._append_agent_log("")
        self._append_agent_log("[大模型]")
        self._append_agent_log(f"intent = {result.get('intent', 'unknown')}")

        self._update_active_scene(normalized_text, result)
        if execution["logs"]:
            self._append_agent_log("")
            self._append_agent_log("[动作]")
            for action_log in execution["logs"]:
                self._append_agent_log(action_log)
                self._log(f"[动作] {action_log}", "device")
        self._append_agent_log("")
        self._append_agent_log("[回复]")
        self._append_agent_log(reply)
        self._log(f"[AI] {reply}", "voice")
        self._speak(reply)

    def _update_active_scene(self, text, result):
        if result.get("intent") != "scene_mode":
            return
        compact = text.replace(" ", "")
        if "睡" in compact:
            self._active_scene = "sleep"
        elif "回家" in compact:
            self._active_scene = "home"
        elif "学习" in compact:
            self._active_scene = "study"

    def _normalize_gesture_name(self, gesture_name: str):
        mapping = {
            "无手势": "无",
            "OK手势": "OK",
            "张开手掌": "手掌",
            "握拳": "握拳",
            "点赞": "点赞",
            "倒赞": "倒赞",
            "V字手势": "V字",
        }
        return mapping.get(gesture_name, gesture_name)

    def _reset_current_gesture(self):
        self._gesture_idle_timer.stop()
        self._last_gesture_name = "无"
        self._status_gesture.set_ok("手势状态：待命")

    # ================================================================
    # 手势 → 设备命令（通过状态机确认后触发）
    # ================================================================

    def _on_gesture_command(self, command: str):
        """处理状态机确认后的设备命令"""
        if command == "light_toggle":
            self.light.toggle()
        elif command == "fan_toggle":
            self.fan.toggle()
        elif command == "ac_temp_up":
            self.ac.increase_temperature()
        elif command == "ac_temp_down":
            self.ac.decrease_temperature()
        elif command == "ac_toggle":
            self._toggle_ac()
        self._stop_gesture_recognition("已识别")

    # ================================================================
    # 语音 → 设备命令（业务逻辑不变）
    # ================================================================

    def _handle_voice_command(self, text: str):
        """语音命令解析 —— 仅增强文本归一化与语义匹配。"""
        raw_text = text.strip()
        normalized_text = normalize_voice_text(raw_text)
        t = normalized_text.replace(" ", "")

        self._log(f"原始识别文本：{raw_text}", "voice")
        self._log(f"归一化文本：{normalized_text}", "voice")

        action, label = parse_voice_intent(normalized_text)
        if action:
            self._log(f"语义解析结果：{label}", "voice")
            success_label = label

            if action == "light_on":
                self.light.turn_on()
            elif action == "light_off":
                self.light.turn_off()
            elif action == "light_brightness_up":
                self.light.set_brightness(self.light.state["brightness"] + 10)
                success_label = f"灯光亮度 {self.light.state['brightness']}%"
            elif action == "light_brightness_down":
                self.light.set_brightness(self.light.state["brightness"] - 10)
                success_label = f"灯光亮度 {self.light.state['brightness']}%"
            elif action == "light_color_cycle":
                self._cycle_light_color()
                success_label = f"灯光颜色 {self.light.state['color']}"
            elif action.startswith("light_color:"):
                self._set_light_color_from_voice(action.split(":", 1)[1])
                success_label = f"灯光颜色 {self.light.state['color']}"
            elif action == "scene_home":
                self._activate_home_mode()
            elif action == "scene_sleep":
                self._activate_sleep_mode()
            elif action == "fan_on":
                self.fan.turn_on()
            elif action == "fan_off":
                self.fan.turn_off()
            elif action == "ac_on":
                self.ac.turn_on()
            elif action == "ac_off":
                self.ac.turn_off()
            elif action == "ac_temp_up":
                self.ac.increase_temperature()
            elif action == "ac_temp_down":
                self.ac.decrease_temperature()

            self._log(f"执行成功：{success_label}", "device")

        # ---- 辅助控制（保留原有逻辑） ----

        # 灯光亮度
        if "亮度" in t or "调亮" in t or "调暗" in t:
            nums = re.findall(r"\d+", normalized_text)
            if nums:
                self.light.set_brightness(int(nums[0]))

        # 空调温度
        if "温度" in t or "度" in t:
            nums = re.findall(r"\d+", normalized_text)
            if nums:
                temp = int(nums[0])
                if 16 <= temp <= 30:
                    self.ac.set_temperature(temp)

        # 空调模式
        if "制冷" in t:
            self.ac.set_mode("cool")
        elif "制热" in t:
            self.ac.set_mode("heat")
        elif "送风" in t:
            self.ac.set_mode("fan")
        elif "自动" in t and any(kw in t for kw in ["空调", "冷气", "制冷", "空调机"]):
            self.ac.set_mode("auto")

        # 风扇风速
        if "风速" in t:
            nums = re.findall(r"\d+", normalized_text)
            if nums:
                self.fan.set_speed(int(nums[0]))
        elif any(kw in t for kw in ["风扇", "电扇", "风"]):
            nums = re.findall(r"\d+", normalized_text)
            if nums:
                self.fan.set_speed(int(nums[0]))

    # ================================================================
    # 全局样式
    # ================================================================

    def _apply_global_style(self):
        c = COLORS  # shorthand
        self.setStyleSheet(f"""
            /* === 全局 === */
            QMainWindow {{
                background-color: {c['bg_dark']};
            }}
            QWidget {{
                background-color: transparent;
                color: {c['text_primary']};
                font-family: {"PingFang SC" if IS_MAC else "Microsoft YaHei"}, "Helvetica Neue", Arial;
            }}

            /* === 标题栏 === */
            #HeaderBar {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c['header_gradient_start']},
                    stop:1 {c['header_gradient_end']});
                border: 1px solid {c['border']};
                border-radius: 16px;
            }}

            #Sidebar {{
                background-color: {c['bg_card']};
                border: 1px solid {c['border']};
                border-radius: 16px;
            }}

            /* === 大时钟/问候卡片 === */
            #HeroCard {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0d1b3e,
                    stop:1 #111d3a);
                border: 1px solid {c['border']};
                border-radius: 20px;
            }}

            /* === 设备卡片 === */
            #DeviceCard {{
                background-color: {c['bg_card']};
                border: 1px solid {c['border']};
                border-radius: 16px;
            }}
            #DeviceCard:hover {{
                border-color: {c['accent_dim']};
            }}

            #SceneCard {{
                background-color: {c['bg_card_alt']};
                border: 1px solid {c['border']};
                border-radius: 14px;
            }}
            #SceneCard:hover {{
                border-color: {c['accent']};
            }}

            /* === 摄像头卡片 === */
            #CameraCard {{
                background-color: {c['bg_card']};
                border: 1px solid {c['camera_border']};
                border-radius: 16px;
            }}

            /* === 日志面板 === */
            #LogPanel {{
                background-color: {c['bg_card']};
                border: 1px solid {c['border']};
                border-radius: 16px;
            }}

            /* === 按钮 === */
            QPushButton {{
                background-color: {c['bg_card_alt']};
                border: 1px solid {c['border']};
                border-radius: 10px;
                padding: 6px 14px;
                font-size: 11px;
                color: {c['text_primary']};
            }}
            QPushButton:hover {{
                background-color: #1e2d5a;
                border-color: {c['accent']};
            }}
            QPushButton:pressed {{
                background-color: #0f1e3a;
            }}
            QPushButton:checked {{
                background-color: {c['accent_dim']};
                border-color: {c['accent']};
                color: #fff;
            }}
            QPushButton:disabled {{
                background-color: {c['bg_card_alt']};
                color: {c['text_dim']};
            }}

            QLineEdit, QTextEdit {{
                background-color: {c['bg_card_alt']};
                border: 1px solid {c['border']};
                border-radius: 12px;
                padding: 8px 10px;
                color: {c['text_primary']};
                selection-background-color: {c['accent_dim']};
            }}

            QLineEdit:focus, QTextEdit:focus {{
                border-color: {c['accent']};
            }}

            /* === 强调按钮 === */
            #AccentButton {{
                background-color: {c['accent_dim']};
                border: 1px solid {c['accent']};
                color: #fff;
                font-weight: bold;
            }}
            #AccentButton:hover {{
                background-color: {c['accent']};
            }}
            #AccentButton:checked {{
                background-color: #e94560;
                border-color: #e94560;
            }}

            #PillButton {{
                background-color: {c['bg_card_alt']};
                border: 1px solid {c['border']};
                border-radius: 14px;
                color: {c['text_primary']};
                padding: 7px 14px;
            }}
            #PillButton:hover {{
                background-color: {c['accent_dim']};
                border-color: {c['accent']};
                color: #ffffff;
            }}

            /* === 分割器 === */
            QSplitter::handle {{
                background-color: {c['border']};
                margin: 0 4px;
            }}

            /* === 滚动区域 === */
            QScrollArea {{
                border: none;
                background: transparent;
            }}

            /* === 状态栏（隐藏，使用自定义状态区） === */
            QStatusBar {{
                background-color: {c['bg_card']};
                color: {c['text_dim']};
                border-top: 1px solid {c['border']};
                font-size: 10px;
            }}

            /* === 工具提示 === */
            QToolTip {{
                background-color: {c['bg_card_alt']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 4px;
            }}
        """)

    # ================================================================
    # 生命周期
    # ================================================================

    def closeEvent(self, event):
        self._log("系统正在关闭...", "warn")
        self._status_sys.set_warn("系统：关闭中")
        if self.gesture_worker:
            self.gesture_worker.stop()
        self.speech_worker.stop()
        if self.gesture_worker:
            self.gesture_worker.wait(3000)
        self.speech_worker.wait(3000)
        event.accept()


# ================================================================
# 入口
# ================================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SmartVoiceSystem")
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
