"""
Action schema, validation helpers, and device action execution.
"""

import json
import re


ALLOWED_INTENTS = {"control_device", "scene_mode", "query_status", "chat", "unknown"}
ALLOWED_DEVICES = {"light", "fan", "air_conditioner"}
ALLOWED_ACTIONS = {"on", "off", "set_temperature", "set_speed"}

DEFAULT_RESULT = {
    "intent": "unknown",
    "actions": [],
    "reply": "我还没有理解这条指令，可以换一种说法试试。",
}


def extract_json_object(text):
    """Parse strict JSON, with a small guard for markdown fenced responses."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return DEFAULT_RESULT.copy()

    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        return DEFAULT_RESULT.copy()
    return value if isinstance(value, dict) else DEFAULT_RESULT.copy()


def validate_agent_result(value):
    result = DEFAULT_RESULT.copy()
    if not isinstance(value, dict):
        return result

    intent = value.get("intent")
    result["intent"] = intent if intent in ALLOWED_INTENTS else "unknown"
    reply = value.get("reply")
    result["reply"] = reply.strip() if isinstance(reply, str) and reply.strip() else DEFAULT_RESULT["reply"]

    actions = []
    for item in value.get("actions", []):
        if not isinstance(item, dict):
            continue
        device = item.get("device")
        action = item.get("action")
        if device not in ALLOWED_DEVICES or action not in ALLOWED_ACTIONS:
            continue
        normalized = {"device": device, "action": action, "value": item.get("value")}
        if action == "set_temperature":
            try:
                normalized["value"] = max(16, min(30, int(normalized["value"])))
            except (TypeError, ValueError):
                continue
        elif action == "set_speed":
            try:
                normalized["value"] = max(0, min(3, int(normalized["value"])))
            except (TypeError, ValueError):
                continue
        else:
            normalized["value"] = None
        actions.append(normalized)

    result["actions"] = actions
    return result


class ActionExecutor:
    """Executes validated LLM actions against a DeviceManager."""

    def __init__(self, device_manager):
        self.device_manager = device_manager

    def execute(self, agent_result):
        result = validate_agent_result(agent_result)
        logs = []

        if result["intent"] == "query_status":
            return {
                "reply": self.device_manager.format_status_reply(),
                "logs": ["status -> query"],
                "result": result,
            }

        for action in result["actions"]:
            self.device_manager.apply_action(action)
            value = "" if action["value"] is None else f" {action['value']}"
            logs.append(f"{action['device']} -> {action['action']}{value}")

        return {"reply": result["reply"], "logs": logs, "result": result}
