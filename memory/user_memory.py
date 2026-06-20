"""
Simple JSON-backed preference memory for AI-SmartHouse.
"""

import json
import os
import re


class UserMemory:
    """Stores lightweight user preferences in memory/user_memory.json."""

    def __init__(self, path=None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.path = path or os.path.join(base_dir, "user_memory.json")
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                value = json.load(file)
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)

    def update_from_text(self, text):
        """Learn preferences such as '我睡觉喜欢空调26度'."""
        compact = re.sub(r"\s+", "", text or "")
        learned = {}

        sleep_match = re.search(r"(睡觉|睡眠).{0,8}(空调|温度)?(\d{2})度?", compact)
        if sleep_match:
            temperature = int(sleep_match.group(3))
            if 16 <= temperature <= 30:
                self.data["sleep_temperature"] = temperature
                learned["sleep_temperature"] = temperature

        if learned:
            self.save()
        return learned

    def get_sleep_temperature(self, default=26):
        value = self.data.get("sleep_temperature", default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return max(16, min(30, value))
