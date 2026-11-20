"""Model-driven tool loop with bounded steps and no write-capable tools."""

import json
from threading import BoundedSemaphore

from . import deepseek, prompts, tools
from .errors import AgentError

_model_slots = BoundedSemaphore(4)
MAX_ROUNDS = 4
MAX_TOOLS = 6


def _history(items: object) -> list[dict]:
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > 6:
        raise AgentError("对话历史最多保留 6 条。", 400)
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise AgentError("对话历史格式无效。", 400)
        if item["role"] not in ("user", "assistant") or not isinstance(item["content"], str) or len(item["content"]) > 500:
            raise AgentError("对话历史格式无效。", 400)
        cleaned.append(item)
    return cleaned


def _call_tool(call: dict) -> tuple[dict, tools.ToolResult | None]:
    try:
        call_id = call["id"]
        function = call["function"]
        name = function["name"]
        arguments = json.loads(function["arguments"])
        if not isinstance(call_id, str) or not call_id or not isinstance(name, str):
            raise ValueError("工具调用格式无效")
        result = tools.execute(name, arguments)
        content = {"data": result.data, "sources": result.sources}
        return {"role": "tool", "tool_call_id": call_id,
                "content": json.dumps(content, ensure_ascii=False)}, result
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        call_id = call.get("id") if isinstance(call, dict) else None
        if not isinstance(call_id, str) or not call_id:
            raise AgentError("模型返回的工具调用格式无效。") from exc
        return {"role": "tool", "tool_call_id": call_id,
                "content": json.dumps({"error": str(exc)}, ensure_ascii=False)}, None


def ask(question: str, history: object = None) -> dict:
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        raise AgentError("请输入 500 字以内的问题。", 400)
    messages = [{"role": "system", "content": prompts.system_prompt()}, *_history(history),
                {"role": "user", "content": question.strip()}]
    if not _model_slots.acquire(blocking=False):
        raise AgentError("Agent 正在处理较多请求，请稍后重试。", 503)
    try:
        used = []
        sources = []
        selected = None
        for round_number in range(MAX_ROUNDS):
            message, finish_reason = deepseek.complete(
                messages, tools.TOOL_SPECS, "required" if round_number == 0 else "auto"
            )
            if finish_reason in ("length", "content_filter", "aborted"):
                raise AgentError("模型未能完成回答，请换一种问法重试。")
            calls = message.get("tool_calls") or []
            if calls:
                if not isinstance(calls, list) or len(used) + len(calls) > MAX_TOOLS:
                    raise AgentError("Agent 工具调用次数已达上限。")
                messages.append({"role": "assistant", "content": message.get("content"),
                                 "tool_calls": calls})
                for call in calls:
                    tool_message, result = _call_tool(call)
                    messages.append(tool_message)
                    if result:
                        used.append(call["function"]["name"])
                        sources.extend(source for source in result.sources if source not in sources)
                        if selected is None or result.intent == "project_plan":
                            selected = result
                continue
            answer = message.get("content")
            if not selected or not isinstance(answer, str) or not answer.strip():
                raise AgentError("模型没有给出有数据依据的回答，请重试。")
            return {"intent": selected.intent, "answer": answer.strip(), "sources": sources,
                    "data": selected.data, "tools_used": used, "model": deepseek.MODEL}
        raise AgentError("Agent 工具调用轮次已达上限，请缩小问题范围。")
    finally:
        _model_slots.release()
