#!/usr/bin/env python3
"""
Standalone DeepSeek connectivity test.

Run:
    python test_deepseek.py
"""

from llm.deepseek_client import DeepSeekClient
import ssl
import sys
import traceback


def main():
    client = DeepSeekClient(model="deepseek-chat", timeout=30)
    try:
        reply = client.chat_text("给我讲一个笑话")
    except Exception as exc:
        print(f"DeepSeek 测试失败：{exc}")
        print("请确认当前运行 python test_deepseek.py 的终端能读取 DEEPSEEK_API_KEY。")
        print("\n诊断信息：")
        print(f"Python 版本: {sys.version}")
        print(f"OpenSSL 版本: {ssl.OPENSSL_VERSION}")
        print("完整 traceback:")
        traceback.print_exc()
        raise SystemExit(1)
    print("\n真实回复：")
    print(reply)


if __name__ == "__main__":
    main()
