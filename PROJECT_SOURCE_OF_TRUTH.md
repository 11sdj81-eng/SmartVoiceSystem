# SmartVoiceSystem Source Of Truth

This is the canonical SmartVoiceSystem project.

Canonical project path:

```text
/Users/sudongjian/Projects/SmartVoiceSystem
```

Do not use:

```text
/Users/sudongjian/Desktop/study/111
```

## Confirmed Project Facts

| Item | Result |
| --- | --- |
| Project name | AI-SmartHouse / SmartVoiceSystem |
| Main entry file | `main.py` |
| GUI framework | PyQt5 |
| `llm/deepseek_client.py` | Present |
| `agent/smart_home_agent.py` | Present |
| `memory/user_memory.py` | Present |
| JSON Action Schema | Present in `agent/action_schema.py` |
| PyQt5 Dashboard | Present in `main.py` |
| Faster-Whisper / PyAudio | Present in `speech_worker.py` and `requirements.txt` |
| MediaPipe gesture recognition | Present in `gesture_worker.py` and `requirements.txt` |
| DeviceManager | Present in `devices.py` |
| SceneManager | Implemented as scene-mode logic in `SmartHomeAgent` and PyQt5 scene handlers, not as a separate `SceneManager` class |

## Notes

- The project uses virtual smart-home devices: light, fan, and air conditioner.
- DeepSeek API is optional at runtime; if `DEEPSEEK_API_KEY` is missing or the API call fails, the Agent falls back to local rule-based planning.
- User preferences are stored locally in `memory/user_memory.json`.
- The old project path must not be used for README content, screenshots, Git commits, or GitHub pushes.
