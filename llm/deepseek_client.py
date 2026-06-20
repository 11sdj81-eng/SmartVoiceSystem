"""
DeepSeek API client for AI-SmartHouse.

The client never stores API keys in code. It reads DEEPSEEK_API_KEY from the
environment and falls back to a caller-provided local result on any failure.
"""

import json
import os
import ssl
import urllib.error
import urllib.request

import certifi
from dotenv import load_dotenv


load_dotenv()


class DeepSeekClient:
    """Small DeepSeek chat-completions client with timeout and fallback support."""

    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, model="deepseek-chat", timeout=12, logger=None):
        self.model = model
        self.timeout = timeout
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.logger = logger
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    @property
    def is_configured(self):
        return bool(self.api_key)

    def _log(self, message):
        if self.logger:
            self.logger(message)
        else:
            print(message)

    def chat_json(self, messages, fallback_result):
        """Return model JSON text, or fallback_result when the remote call fails."""
        if not self.api_key:
            self._log("[LLM ERROR] DEEPSEEK_API_KEY is not configured; using fallback")
            return fallback_result

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            self._log(f"[LLM] Calling DeepSeek API: {self.API_URL} model={self.model}")
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self.ssl_context,
            ) as response:
                body = response.read().decode("utf-8")
            parsed = json.loads(body)
            content = parsed["choices"][0]["message"]["content"]
            if not content:
                self._log("[LLM ERROR] Empty DeepSeek response; using fallback")
                return fallback_result
            self._log(f"[LLM] Response: {content}")
            return content
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._log(f"[LLM ERROR] HTTP {exc.code}: {detail}; using fallback")
            return fallback_result
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, OSError) as exc:
            self._log(f"[LLM ERROR] {type(exc).__name__}: {exc}; using fallback")
            return fallback_result

    def chat_text(self, prompt, system_prompt="你是一个友好的中文助手。"):
        """Return a normal text response and raise errors for standalone tests."""
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        self._log(f"[LLM] Calling DeepSeek API: {self.API_URL} model={self.model}")
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self.ssl_context,
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._log(f"[LLM ERROR] HTTP {exc.code}: {detail}")
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._log(f"[LLM ERROR] {type(exc).__name__}: {exc}")
            raise

        parsed = json.loads(body)
        content = parsed["choices"][0]["message"]["content"]
        self._log(f"[LLM] Response: {content}")
        return content

    def check_online(self):
        """Probe DeepSeek availability with a tiny chat request."""
        if not self.api_key:
            return False, "DEEPSEEK_API_KEY is not configured"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "只回复 OK。"},
                {"role": "user", "content": "ping"},
            ],
            "temperature": 0,
            "max_tokens": 4,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=min(self.timeout, 8),
                context=self.ssl_context,
            ) as response:
                body = response.read().decode("utf-8")
            parsed = json.loads(body)
            content = parsed["choices"][0]["message"]["content"]
            return bool(content), content or "empty response"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return False, f"HTTP {exc.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, OSError) as exc:
            return False, f"{type(exc).__name__}: {exc}"
