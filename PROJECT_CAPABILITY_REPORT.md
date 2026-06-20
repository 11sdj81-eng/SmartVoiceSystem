# PROJECT CAPABILITY REPORT — AI-SmartHouse v3.2

**扫描路径**: `/Users/sudongjian/Projects/SmartVoiceSystem`
**项目名称**: AI-SmartHouse（小度式中文智能家居 Agent 中控 Demo）
**版本**: v3.2
**扫描日期**: 2026-06-20

---

## 1. 核心能力判定

| 能力 | 状态 | 实现位置 |
|------|:----:|----------|
| **DeepSeek API** | ✅ | `llm/deepseek_client.py` — 完整 chat/completions 客户端，含 JSON mode、超时、SSL、fallback |
| **Agent** | ✅ | `agent/smart_home_agent.py` — 自然语言→结构化 JSON 动作规划，含本地 fallback |
| **user_memory** | ✅ | `memory/user_memory.py` — JSON 持久化用户偏好（已学习：睡眠空调 28°C） |
| **JSON Action Schema** | ✅ | `agent/action_schema.py` — strict JSON schema 验证，intent+actions+reply 三要素 |
| **SceneManager** | ✅ | `agent/smart_home_agent.py` — 回家/睡眠/学习/节能 四种场景，由 Agent 调度 |

---

## 2. 技术栈

| 层级 | 技术 |
|------|------|
| **GUI 框架** | PyQt5（深色科技蓝主题，支持一键切换浅色） |
| **AI/LLM** | DeepSeek API（`deepseek-chat` 模型，JSON mode，temperature=0.1） |
| **语音识别** | Faster-Whisper + PyAudio（16000Hz 录音，中文转写，VAD 过滤） |
| **手势识别** | OpenCV + MediaPipe HandLandmarker（21 点关键点，7 种手势分类，状态机防抖） |
| **TTS** | macOS `say` 命令（跨平台兼容） |
| **数据持久化** | JSON 本地文件（`memory/user_memory.json`） |
| **环境管理** | python-dotenv（`.env` 管理 API Key） |
| **SSL** | certifi 证书捆绑 |
| **语言** | Python 3 |

---

## 3. 完整功能清单

### 3.1 大模型 Agent
- ✅ 自然语言 → 严格 JSON 动作指令（`{"intent", "actions", "reply"}`）
- ✅ 5 种 intent：`control_device` / `scene_mode` / `query_status` / `chat` / `unknown`
- ✅ 3 种设备：`light` / `fan` / `air_conditioner`
- ✅ 4 种动作：`on` / `off` / `set_temperature` / `set_speed`
- ✅ DeepSeek API 异常时自动切换本地规则模式（`_fallback_plan`）
- ✅ 本地规则覆盖：热→开风扇、冷→调高空调、温度/风速数字提取、场景关键词匹配

### 3.2 语音交互
- ✅ 唤醒词：小智小智 / 智能管家 / 你好管家
- ✅ PyAudio 实时录音 → Faster-Whisper 转写
- ✅ 繁体自动归一化为简体
- ✅ TTS 语音回复（macOS `say`）
- ✅ QThread 后台线程，不阻塞 GUI

### 3.3 手势识别
- ✅ 7 种手势分类：张开手掌/握拳/点赞/倒赞/V字/OK/食指朝上
- ✅ OK 手势唤醒机制（连续 20 帧确认）
- ✅ 功能手势需要连续 10 帧确认
- ✅ 完整状态机：IDLE → WAKE_CONFIRM → CONTROL(5s) → EXECUTED → COOLDOWN(2s) → IDLE
- ✅ 手势去抖（1 秒内同手势只上报一次）
- ✅ 手势命令映射：手掌→灯光、握拳→风扇、点赞→+1°C、倒赞→-1°C、V字→空调

### 3.4 虚拟设备控制
- ✅ 灯光：开关、亮度(0-100)、7 种颜色
- ✅ 风扇：开关、风速(0-3 档)
- ✅ 空调：开关、温度(16-30°C)、4 种模式(制冷/制热/送风/自动)、风速(1-3 档)
- ✅ DeviceManager 统一管理，pyqtSignal 状态变更通知

### 3.5 场景模式
- ✅ 回家模式：开灯 + 空调 26°C + 关风扇
- ✅ 睡眠模式：关灯 + 关风扇 + 空调设为偏好温度（从 user_memory 读取）
- ✅ 学习模式：开灯 + 空调 26°C + 关风扇
- ✅ 节能模式

### 3.6 用户偏好记忆
- ✅ 从对话中学习偏好（如 "我睡觉喜欢空调 28 度"）
- ✅ 正则提取睡眠温度偏好
- ✅ 持久化到 `memory/user_memory.json`
- ✅ 当前记忆：`{"sleep_temperature": 28}`

### 3.7 GUI Dashboard
- ✅ 顶部 Header：产品名称、系统状态指示灯（DeepSeek 在线/语音待命/摄像头）
- ✅ 左侧家庭信息栏：宿舍、模式、状态
- ✅ 主区域：大时钟/问候卡片（60px 时间）、语音管家卡片、设备卡片、场景卡片
- ✅ 智能管家对话区：自然语言输入 + Agent 日志
- ✅ 动作日志与辅助交互：设备操作日志 + 手势触发 + 摄像头预览
- ✅ 深色科技蓝主题 + 一键切换浅色

---

## 4. 项目文件清单

| 文件 | 大小 | 功能 |
|------|------|------|
| `main.py` | 75.7 KB | PyQt5 主界面 + 完整 GUI 逻辑 |
| `devices.py` | 7.6 KB | 虚拟设备类 (Light/Fan/AC) + DeviceManager |
| `agent/action_schema.py` | 4.1 KB | JSON Schema 验证 + ActionExecutor |
| `agent/smart_home_agent.py` | 8.7 KB | LLM Agent + 本地 fallback |
| `llm/deepseek_client.py` | 5.5 KB | DeepSeek API 客户端 |
| `memory/user_memory.py` | 1.5 KB | 用户偏好记忆 |
| `memory/user_memory.json` | 30 B | 持久化数据 |
| `speech_worker.py` | 7.4 KB | Faster-Whisper 语音识别线程 |
| `gesture_worker.py` | 18.8 KB | MediaPipe 手势识别线程 + 状态机 |
| `test_deepseek.py` | 833 B | API 独立测试 |
| `requirements.txt` | 595 B | 依赖清单 |
| `.env.example` | 44 B | API Key 模板 |

---

## 5. 与 Desktop/study/SmartVoiceSystem 对比

| 维度 | `~/Desktop/study/SmartVoiceSystem` | `~/Projects/SmartVoiceSystem` |
|------|:---:|:---:|
| **版本** | v1.0 | v3.2 (AI-SmartHouse) |
| **GUI 框架** | Tkinter | PyQt5 |
| **AI/LLM** | ❌ 无 | ✅ DeepSeek API |
| **Agent** | ❌ 无 | ✅ SmartHomeAgent |
| **user_memory** | ❌ 无 | ✅ JSON 持久化 |
| **JSON Action Schema** | ❌ 仅 README 提及 | ✅ 完整实现 |
| **语音识别** | SpeechRecognition | Faster-Whisper + PyAudio |
| **手势识别** | 基础 OpenCV | MediaPipe + 状态机防抖 |
| **场景模式** | 3 种 (回家/睡眠/离家) | 4 种 (回家/睡眠/学习/节能) |
| **设备类型** | 2 种 (灯光/空调) | 3 种 (灯光/风扇/空调) |
| **产品化程度** | 原型 | 产品级 Dashboard |

---

## 6. 结论

**`/Users/sudongjian/Projects/SmartVoiceSystem` 是真正的 SmartVoiceSystem v2.0+（AI-SmartHouse v3.2）**，完整实现了简历所需的全部核心能力：

- ✅ DeepSeek API 驱动的大模型 Agent
- ✅ 自然语言 → JSON Action Schema 解析
- ✅ 用户偏好记忆 (user_memory)
- ✅ 语音 + 手势 + GUI 多模态交互
- ✅ PyQt5 产品级 Dashboard
- ✅ API 异常 fallback 机制

可以直接将此版本用于简历展示和面试准备。
