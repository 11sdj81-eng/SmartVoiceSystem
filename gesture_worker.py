"""
手势识别工作线程 —— OpenCV 摄像头采集 + MediaPipe HandLandmarker + 自定义手势分类。
将关键点绘制后的帧发送给 UI，同时检测到手势时发出信号。

手势唤醒机制：
  👌 OK手势  → 唤醒（连续20帧确认）
  ✋ 张开手掌 → 灯光开关
  ✊ 握拳     → 风扇开关
  👍 点赞     → 空调+1℃
  👎 倒赞     → 空调-1℃
  ✌️ V字手势  → 空调开关

状态机：IDLE → WAKE_CONFIRM(20帧) → CONTROL(5秒) → EXECUTED → COOLDOWN(2秒) → IDLE

适配 MediaPipe 0.10.35+ 新版 tasks API。
"""

import math
import os
import time
import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


# ================================================================
# 摄像头配置
# ================================================================

CAMERA_INDEX = 0  # 固定使用内置摄像头


# ================================================================
# 状态机常量
# ================================================================

STATE_IDLE = 0          # 待机，等待唤醒手势
STATE_WAKE_CONFIRM = 1  # 检测到唤醒手势，累积确认帧
STATE_CONTROL = 2       # 控制模式，接受功能手势
STATE_EXECUTED = 3      # 命令已执行
STATE_COOLDOWN = 4      # 命令执行后冷却

STATE_LABELS = {
    STATE_IDLE: "待机中",
    STATE_WAKE_CONFIRM: "唤醒确认中",
    STATE_CONTROL: "控制模式",
    STATE_EXECUTED: "已执行",
    STATE_COOLDOWN: "冷却中",
}

# 唤醒手势 ID
WAKEUP_GESTURE = 6  # 👌 OK手势

# 功能手势 → 命令映射（仅在控制模式下生效）
FUNC_GESTURE_COMMANDS = {
    1: "light_toggle",    # 张开手掌 → 灯光
    2: "fan_toggle",      # 握拳     → 风扇
    3: "ac_temp_up",      # 点赞     → 空调+1℃
    4: "ac_temp_down",    # 倒赞     → 空调-1℃
    5: "ac_toggle",       # V字手势  → 空调开关
}

# 帧数 / 时间阈值
WAKEUP_FRAMES = 20        # 唤醒需连续 20 帧
FUNC_FRAMES = 10          # 功能手势需连续 10 帧
CONTROL_TIMEOUT = 5.0     # 控制模式持续 5 秒
COOLDOWN_DURATION = 2.0   # 执行后冷却 2 秒
GESTURE_DEBOUNCE_SECONDS = 1.0  # 同一种手势 1 秒内只上报一次


class GestureWorker(QThread):
    """手势识别线程 — 摄像头帧采集 → MediaPipe HandLandmarker → 手势分类 → 状态机 → 信号通知主线程"""

    # ---- 信号 ----
    frame_ready = pyqtSignal(np.ndarray)        # 绘制后的帧（供 CameraWidget 显示）
    gesture_detected = pyqtSignal(str, float)   # 手势名称 + 置信度（当前原始检测结果）
    gesture_ignored = pyqtSignal(str)            # 去抖忽略的手势名称
    command_triggered = pyqtSignal(str)          # 状态机确认后的设备命令
    status_changed = pyqtSignal(str)             # 状态文本
    error_occurred = pyqtSignal(str)             # 错误信息

    # 手势名称映射
    GESTURE_NAMES = {
        0: "无手势",
        1: "张开手掌",
        2: "握拳",
        3: "点赞",
        4: "倒赞",
        5: "V字手势",
        6: "OK手势",
        7: "食指朝上",
    }

    # 功能手势中文名（用于日志/UI）
    FUNC_GESTURE_LABELS = {
        1: "张开手掌 → 灯光",
        2: "握拳 → 风扇",
        3: "点赞 → 空调+1℃",
        4: "倒赞 → 空调-1℃",
        5: "V字手势 → 空调开关",
    }

    # 模型路径（相对于项目根目录）
    MODEL_FILENAME = "hand_landmarker.task"

    def __init__(self, model_dir: str = None):
        """
        Args:
            model_dir: 模型文件所在目录，默认为项目根目录下的 models/
        """
        super().__init__()
        self._running = True
        self._detector = None
        self._mp_module = None
        self._model_dir = model_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "models"
        )
        self._gesture_last_emit_times = {}
        self._gesture_last_ignored_times = {}

    # ================================================================
    # 公开接口（主线程调用）
    # ================================================================

    def stop(self):
        self._running = False

    # ================================================================
    # 内部逻辑（在工作线程中执行）
    # ================================================================

    def _load_model(self):
        """使用新版 MediaPipe tasks API 加载 HandLandmarker"""
        try:
            import mediapipe as mp
            from mediapipe.tasks.python.vision import (
                HandLandmarker,
                HandLandmarkerOptions,
                RunningMode,
            )
            from mediapipe.tasks.python.core.base_options import BaseOptions

            self._mp_module = mp

            model_path = os.path.join(self._model_dir, self.MODEL_FILENAME)
            if not os.path.exists(model_path):
                self.error_occurred.emit(
                    f"手势模型文件未找到: {model_path}\n"
                    f"请从以下地址下载并放入 models/ 目录:\n"
                    f"https://storage.googleapis.com/mediapipe-models/"
                    f"hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
                )
                return False

            self.status_changed.emit("正在加载手势识别模型（MediaPipe HandLandmarker）...")

            options = HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                running_mode=RunningMode.LIVE_STREAM,
                num_hands=1,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                result_callback=self._on_result_callback,
            )

            self._detector = HandLandmarker.create_from_options(options)
            self.status_changed.emit("✅ 手势识别模型就绪")
            return True

        except Exception as e:
            self.error_occurred.emit(f"手势模型加载失败: {e}")
            return False

    # ---- MediaPipe 异步结果回调 ----
    def __init_callback_fields__(self):
        """在 _load_model 之后初始化回调相关字段"""
        self._latest_result = None
        self._result_timestamp = 0

    def _on_result_callback(self, result, image, timestamp_ms):
        """HandLandmarker 的异步结果回调（在内部线程中调用）"""
        self._latest_result = result
        self._result_timestamp = timestamp_ms

    # ---- 手指伸直判断（适配新版 NormalizedLandmark） ----
    @staticmethod
    def _get_finger_states(landmark_list):
        """
        判断每根手指是否伸直。
        参数 landmark_list: list[NormalizedLandmark]，长度 21
        返回: [拇指, 食指, 中指, 无名指, 小指] — True 表示伸直

        拇指使用 2D 欧氏距离（旋转不变），其余四指使用 y 坐标比较。
        """
        tips = [4, 8, 12, 16, 20]   # 指尖
        pips = [3, 6, 10, 14, 18]   # 第二关节
        mcp  = [2, 5, 9, 13, 17]    # 掌指关节

        states = []

        # 拇指：使用 2D 欧氏距离（同时考虑 x 和 y，旋转不变）
        d_tip = math.hypot(
            landmark_list[tips[0]].x - landmark_list[mcp[0]].x,
            landmark_list[tips[0]].y - landmark_list[mcp[0]].y,
        )
        d_ip = math.hypot(
            landmark_list[pips[0]].x - landmark_list[mcp[0]].x,
            landmark_list[pips[0]].y - landmark_list[mcp[0]].y,
        )
        states.append(d_tip > d_ip * 1.2)

        # 其余四指：指尖 y 坐标在 PIP 上方即为伸直
        for i in range(1, 5):
            states.append(
                landmark_list[tips[i]].y < landmark_list[pips[i]].y - 0.02
            )

        return states

    # ---- 手势分类 ----
    @classmethod
    def classify_gesture(cls, landmark_list) -> int:
        """
        基于手指伸直状态分类手势。

        优先级顺序（从高到低）：
          1. OPEN_PALM  — 五指全伸
          2. FIST       — 四指全曲（拇指可伸可曲，容忍真实握拳时拇指外露）
          3. V_SIGN     — 食指+中指伸直，无名指+小指弯曲
          4. THUMBS_UP  — 仅拇指伸直 + 拇指明显向上
          5. THUMBS_DOWN— 仅拇指伸直 + 拇指明显向下
          6. OK         — 拇指+食指伸直
          7. INDEX_UP   — 仅食指伸直
          8. OTHER      — 无法识别

        返回 gesture_id: 0=无, 1=张开手掌, 2=握拳, 3=点赞, 4=倒赞,
                        5=V字, 6=OK, 7=食指朝上
        """
        states = cls._get_finger_states(landmark_list)
        thumb, index, middle, ring, pinky = states
        finger_count = sum(states)

        # 1. 张开手掌：五指全伸
        if finger_count == 5:
            return 1

        # 2. 四指全曲（不要求拇指弯曲）
        if not any([index, middle, ring, pinky]):
            # 拇指明显朝上 → 点赞
            if thumb and landmark_list[4].y < landmark_list[3].y - 0.04:
                return 3
            # 拇指明显朝下 → 倒赞
            if thumb and landmark_list[4].y > landmark_list[3].y + 0.04:
                return 4
            # 方向不明确或拇指未伸出 → 握拳
            return 2

        # 3. V 字手势：食指+中指伸直，无名指+小指弯曲（不依赖拇指）
        if index and middle and not ring and not pinky:
            return 5

        # 4. OK 手势：拇指+食指伸直，其余三指弯曲
        if thumb and index and not any([middle, ring, pinky]):
            return 6

        # 5. 食指朝上：仅食指伸直
        if index and not any([thumb, middle, ring, pinky]):
            return 7

        # 6. 无法识别
        return 0

    # ================================================================
    # 状态机
    # ================================================================

    def _init_state_machine(self):
        """初始化 / 重置状态机变量"""
        self._sm_state = STATE_IDLE
        self._sm_frame_count = 0         # 当前目标手势的连续帧计数
        self._sm_target_gesture = 0      # 当前累积的功能手势 ID
        self._sm_state_start_time = 0.0  # 进入 CONTROL / COOLDOWN 的时间戳

    def _run_state_machine(self, gesture_id: int):
        """
        状态机主逻辑。每帧调用一次。

        状态转换：
          IDLE → WAKE_CONFIRM（检测到唤醒手势）
          WAKE_CONFIRM → CONTROL（连续 20 帧确认） / IDLE（中断）
          CONTROL → EXECUTED（功能手势 10 帧确认） / IDLE（5 秒超时）
          EXECUTED → COOLDOWN（立即）
          COOLDOWN → IDLE（2 秒后）

        返回: (status_msg: str | None, command: str | None)
        """
        status_msg = None
        command = None

        if self._sm_state == STATE_IDLE:
            if gesture_id == WAKEUP_GESTURE:
                self._sm_state = STATE_WAKE_CONFIRM
                self._sm_frame_count = 1
                self._sm_target_gesture = WAKEUP_GESTURE
                status_msg = f"🔔 检测到唤醒手势... ({self._sm_frame_count}/{WAKEUP_FRAMES})"

        elif self._sm_state == STATE_WAKE_CONFIRM:
            if gesture_id == WAKEUP_GESTURE:
                self._sm_frame_count += 1
                if self._sm_frame_count >= WAKEUP_FRAMES:
                    self._sm_state = STATE_CONTROL
                    self._sm_frame_count = 0
                    self._sm_target_gesture = 0
                    self._sm_state_start_time = time.time()
                    status_msg = "🎯 控制模式已激活"
                elif self._sm_frame_count % 5 == 0:
                    status_msg = f"🔔 唤醒确认中... ({self._sm_frame_count}/{WAKEUP_FRAMES})"
            else:
                if self._sm_frame_count > 3:
                    status_msg = "↩️ 唤醒取消（手势中断）"
                self._sm_state = STATE_IDLE
                self._sm_frame_count = 0
                self._sm_target_gesture = 0

        elif self._sm_state == STATE_CONTROL:
            elapsed = time.time() - self._sm_state_start_time
            if elapsed >= CONTROL_TIMEOUT:
                self._sm_state = STATE_IDLE
                self._sm_frame_count = 0
                self._sm_target_gesture = 0
                status_msg = "⏰ 控制模式超时，已退出"
            elif gesture_id in FUNC_GESTURE_COMMANDS:
                if gesture_id == self._sm_target_gesture:
                    self._sm_frame_count += 1
                    if self._sm_frame_count >= FUNC_FRAMES:
                        command = FUNC_GESTURE_COMMANDS[gesture_id]
                        label = self.FUNC_GESTURE_LABELS.get(
                            gesture_id, self.GESTURE_NAMES[gesture_id]
                        )
                        status_msg = f"✅ 命令已执行: {label}"
                        self._sm_state = STATE_EXECUTED
                        self._sm_frame_count = 0
                        self._sm_target_gesture = 0
                else:
                    self._sm_target_gesture = gesture_id
                    self._sm_frame_count = 1
            else:
                if self._sm_target_gesture != 0:
                    self._sm_target_gesture = 0
                    self._sm_frame_count = 0

        elif self._sm_state == STATE_EXECUTED:
            # 立即转入冷却
            self._sm_state = STATE_COOLDOWN
            self._sm_state_start_time = time.time()

        elif self._sm_state == STATE_COOLDOWN:
            elapsed = time.time() - self._sm_state_start_time
            if elapsed >= COOLDOWN_DURATION:
                self._sm_state = STATE_IDLE
                self._sm_frame_count = 0
                self._sm_target_gesture = 0
                status_msg = "🔄 冷却完成，可以再次唤醒（👌 OK手势）"

        return status_msg, command

    def _should_emit_gesture(self, gesture_id: int):
        """Return True once per gesture per debounce window."""
        now = time.time()
        last_emit = self._gesture_last_emit_times.get(gesture_id, 0.0)
        if now - last_emit >= GESTURE_DEBOUNCE_SECONDS:
            self._gesture_last_emit_times[gesture_id] = now
            return True

        last_ignored = self._gesture_last_ignored_times.get(gesture_id, 0.0)
        if now - last_ignored >= GESTURE_DEBOUNCE_SECONDS:
            self._gesture_last_ignored_times[gesture_id] = now
            self.gesture_ignored.emit(self.GESTURE_NAMES.get(gesture_id, "?"))
        return False

    # ================================================================
    # 帧叠加状态信息
    # ================================================================

    def _draw_overlay(self, frame: np.ndarray, gesture_id: int) -> np.ndarray:
        """Keep camera image clean; recognition result is shown in the UI below."""
        return frame

    # ================================================================
    # 线程主循环
    # ================================================================

    def run(self):
        # --- 1. 加载模型 ---
        if not self._load_model():
            return
        self.__init_callback_fields__()

        # --- 2. 初始化状态机 ---
        self._init_state_machine()

        # --- 3. 打开摄像头 ---
        print(f"Using camera index: {CAMERA_INDEX}")
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if not cap.isOpened():
            self.error_occurred.emit(f"无法打开摄像头（索引 {CAMERA_INDEX}，请检查权限）")
            self.status_changed.emit("❌ 摄像头不可用")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.status_changed.emit(f"✅ 手势识别运行中（摄像头 #{CAMERA_INDEX}）")
        self.status_changed.emit("💡 OK手势 👌 可唤醒控制模式")

        frame_counter = 0

        # --- 4. 主循环 ---
        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # 水平镜像（更自然）
            frame = cv2.flip(frame, 1)

            # 转换为 MediaPipe Image 格式（SRGB）
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = self._mp_module.Image(
                image_format=self._mp_module.ImageFormat.SRGB,
                data=rgb,
            )

            # 异步检测：传入帧，结果通过回调在内部线程中返回
            self._detector.detect_async(mp_image, timestamp_ms=frame_counter)
            frame_counter += 1

            # 转回 BGR 用于显示
            display = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            gesture_id = 0

            # 取最新结果
            result = self._latest_result
            if result and result.hand_landmarks:
                from mediapipe.tasks.python.vision import (
                    HandLandmarksConnections,
                    drawing_utils,
                )

                for landmark_list in result.hand_landmarks:
                    # 绘制手部关键点与连线
                    drawing_utils.draw_landmarks(
                        display,
                        landmark_list,
                        HandLandmarksConnections.HAND_CONNECTIONS,
                    )
                    gesture_id = self.classify_gesture(landmark_list)

            # ---- 状态机处理 ----
            status_msg, command = self._run_state_machine(gesture_id)

            # 发送状态消息
            if status_msg:
                self.status_changed.emit(status_msg)

            # 发送设备命令
            if command:
                self.command_triggered.emit(command)

            # 发送当前手势信息（供 UI 显示原始检测结果）
            if gesture_id > 0:
                if self._should_emit_gesture(gesture_id):
                    self.gesture_detected.emit(
                        self.GESTURE_NAMES[gesture_id], 0.85
                    )

            # ---- 叠加状态信息到帧 ----
            display = self._draw_overlay(display, gesture_id)

            # 发送带标注的帧供 UI 显示
            self.frame_ready.emit(display)

            # 控制约 30 fps
            time.sleep(0.01)

        # --- 5. 清理 ---
        cap.release()
        if self._detector:
            self._detector.close()
