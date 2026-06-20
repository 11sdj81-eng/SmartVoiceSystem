"""
LLM-powered smart-home agent with local fallback intent planning.
"""

import json
import re

from agent.action_schema import extract_json_object, validate_agent_result
from llm.deepseek_client import DeepSeekClient
from memory.user_memory import UserMemory


TEXT_TRANSLATION = str.maketrans({
    "開": "开",
    "關": "关",
    "閉": "闭",
    "燈": "灯",
    "風": "风",
    "電": "电",
    "調": "调",
    "溫": "温",
    "熱": "热",
    "啟": "启",
    "學": "学",
    "習": "习",
})


class SmartHomeAgent:
    """Turns natural language into strict smart-home action JSON."""

    def __init__(self, memory=None, llm_client=None, logger=None):
        self.memory = memory or UserMemory()
        self.llm_client = llm_client or DeepSeekClient(logger=logger)

    def plan(self, user_text, device_status=None):
        learned = self.memory.update_from_text(user_text)
        compact = self._normalize(user_text)
        if learned and any(keyword in compact for keyword in ("喜欢", "习惯", "偏好")):
            return {
                "intent": "chat",
                "actions": [],
                "reply": f"已记住：睡觉时空调 {learned['sleep_temperature']} 度。",
            }
        fallback = self._fallback_plan(user_text, device_status)
        messages = self._build_messages(user_text, device_status)
        raw = self.llm_client.chat_json(messages, json.dumps(fallback, ensure_ascii=False))
        result = validate_agent_result(extract_json_object(raw))
        return self._apply_memory(user_text, result)

    def _build_messages(self, user_text, device_status):
        schema_hint = {
            "intent": "control_device | scene_mode | query_status | chat | unknown",
            "actions": [
                {
                    "device": "light | fan | air_conditioner",
                    "action": "on | off | set_temperature | set_speed",
                    "value": None,
                }
            ],
            "reply": "给用户看的自然语言回复",
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是 AI-SmartHouse 的智能家居 Agent。"
                    "只输出严格 JSON，不要输出 Markdown。"
                    "device 只能是 light、fan、air_conditioner。"
                    "action 只能是 on、off、set_temperature、set_speed。"
                    "无法控制设备时 intent 使用 chat 或 unknown。"
                    "规则：用户说“我有点热”时优先打开 fan。"
                    "用户说“我要睡觉了”时使用 scene_mode，关闭 light 和 fan，并设置 air_conditioner 温度。"
                    "用户聊天或讲笑话时使用 chat，actions 为空。"
                    f"JSON 格式: {json.dumps(schema_hint, ensure_ascii=False)}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户输入: {user_text}\n"
                    f"当前设备状态: {json.dumps(device_status or {}, ensure_ascii=False)}\n"
                    f"用户偏好记忆: {json.dumps(self.memory.data, ensure_ascii=False)}"
                ),
            },
        ]

    def _apply_memory(self, user_text, result):
        compact = self._normalize(user_text)
        if any(keyword in compact for keyword in ("睡觉", "睡眠", "我要睡了")):
            sleep_temperature = self.memory.get_sleep_temperature(26)
            for action in result["actions"]:
                if action["device"] == "air_conditioner" and action["action"] == "set_temperature":
                    action["value"] = sleep_temperature
            if not any(a["device"] == "air_conditioner" and a["action"] == "set_temperature" for a in result["actions"]):
                result["actions"].append({
                    "device": "air_conditioner",
                    "action": "set_temperature",
                    "value": sleep_temperature,
                })
        return result

    def _fallback_plan(self, user_text, device_status):
        text = self._normalize(user_text)
        numbers = [int(n) for n in re.findall(r"\d+", text)]

        preference = self.memory.update_from_text(user_text)
        if preference and any(keyword in text for keyword in ("喜欢", "习惯", "偏好")):
            return {
                "intent": "chat",
                "actions": [],
                "reply": f"已记住：睡觉时空调 {preference['sleep_temperature']} 度。",
            }

        scene_patterns = [
            (("睡觉", "睡眠", "我要睡了"), self._sleep_scene),
            (("学习模式", "学习"), self._study_scene),
            (("回家模式", "回家"), self._home_scene),
        ]
        for keywords, builder in scene_patterns:
            if any(keyword in text for keyword in keywords):
                return builder()

        if any(keyword in text for keyword in ("状态", "查询", "设备状态", "当前设备")):
            return {"intent": "query_status", "actions": [], "reply": "正在查询当前设备状态。"}

        if any(keyword in text for keyword in ("笑话", "讲个笑话", "讲一个笑话")):
            return {
                "intent": "chat",
                "actions": [],
                "reply": "当然。为什么智能灯泡从不迷路？因为它总能找到自己的开关。",
            }

        direct_rules = [
            (("灯", "灯光", "电灯"), "light"),
            (("风扇", "电扇"), "fan"),
            (("空调", "冷气"), "air_conditioner"),
        ]
        switch_rules = [("off", ("关闭", "关掉", "停止", "关")), ("on", ("打开", "开启", "启动", "开"))]

        for device_keywords, device in direct_rules:
            if any(keyword in text for keyword in device_keywords):
                for action, action_keywords in switch_rules:
                    if any(keyword in text for keyword in action_keywords):
                        return self._single_action(device, action)

        if "热" in text:
            return {
                "intent": "control_device",
                "actions": [{"device": "fan", "action": "on", "value": None}],
                "reply": "已为你打开风扇。",
            }
        if "冷" in text:
            return {
                "intent": "control_device",
                "actions": [{"device": "air_conditioner", "action": "set_temperature", "value": 28}],
                "reply": "已为你把空调调高到 28 度。",
            }
        if "风速" in text and numbers:
            return {
                "intent": "control_device",
                "actions": [{"device": "fan", "action": "set_speed", "value": numbers[0]}],
                "reply": f"已将风扇风速设置为 {numbers[0]} 档。",
            }
        if ("温度" in text or "度" in text) and numbers:
            return {
                "intent": "control_device",
                "actions": [{"device": "air_conditioner", "action": "set_temperature", "value": numbers[0]}],
                "reply": f"已将空调温度设置为 {numbers[0]} 度。",
            }
        return {
            "intent": "unknown",
            "actions": [],
            "reply": "我还没有理解这条指令，可以试试说“打开灯”或“我要睡觉了”。",
        }

    def _single_action(self, device, action):
        names = {"light": "灯", "fan": "风扇", "air_conditioner": "空调"}
        verbs = {"on": "打开", "off": "关闭"}
        return {
            "intent": "control_device",
            "actions": [{"device": device, "action": action, "value": None}],
            "reply": f"已为你{verbs[action]}{names[device]}。",
        }

    def _sleep_scene(self):
        temperature = self.memory.get_sleep_temperature(26)
        return {
            "intent": "scene_mode",
            "actions": [
                {"device": "light", "action": "off", "value": None},
                {"device": "fan", "action": "off", "value": None},
                {"device": "air_conditioner", "action": "set_temperature", "value": temperature},
            ],
            "reply": "已为你切换到睡眠模式。",
        }

    def _study_scene(self):
        return {
            "intent": "scene_mode",
            "actions": [
                {"device": "light", "action": "on", "value": None},
                {"device": "fan", "action": "off", "value": None},
                {"device": "air_conditioner", "action": "set_temperature", "value": 26},
            ],
            "reply": "已为你开启学习模式。",
        }

    def _home_scene(self):
        return {
            "intent": "scene_mode",
            "actions": [
                {"device": "light", "action": "on", "value": None},
                {"device": "air_conditioner", "action": "set_temperature", "value": 26},
                {"device": "fan", "action": "off", "value": None},
            ],
            "reply": "已为你切换到回家模式。",
        }

    @staticmethod
    def _normalize(text):
        return re.sub(r"\s+", "", (text or "").translate(TEXT_TRANSLATION))
