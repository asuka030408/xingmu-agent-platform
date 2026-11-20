"""Small DeepSeek Chat Completions adapter; no key is stored in source code."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import deepseek_api_key
from .errors import AgentError

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"


def configured() -> bool:
    return bool(deepseek_api_key())


def complete(messages: list[dict], tools: list[dict], tool_choice: str) -> tuple[dict, str | None]:
    key = deepseek_api_key()
    if not key:
        raise AgentError("DeepSeek API Key 未配置，请在本机配置后重试。", 503)
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "thinking": {"type": "disabled"},
        "max_tokens": 1200,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    request = Request(API_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(2_000_001)
    except HTTPError as exc:
        if exc.code == 401:
            raise AgentError("DeepSeek API Key 无效，请检查本机配置。", 503) from exc
        if exc.code == 429:
            raise AgentError("DeepSeek 请求过于频繁，请稍后重试。", 503) from exc
        raise AgentError(f"DeepSeek API 返回 HTTP {exc.code}，请稍后重试。", 502) from exc
    except (URLError, TimeoutError) as exc:
        raise AgentError("无法连接 DeepSeek，请检查网络后重试。", 503) from exc
    if len(raw) > 2_000_000:
        raise AgentError("DeepSeek 响应过大，已停止处理。")
    try:
        choice = json.loads(raw)["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError("invalid message")
        return message, choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AgentError("DeepSeek 响应格式无法识别。") from exc
