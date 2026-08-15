"""ASR partial 文字 → 指令 action 的比對器。

比對走 pinyin（忽略聲調）子字串，容忍同音錯字。
同一 utterance（兩次 endpoint 之間）每個 action 只觸發一次，
另有跨 utterance 的 per-action 冷卻時間。
"""
from __future__ import annotations

from pypinyin import lazy_pinyin

from .config import Command


def _pin(text: str) -> str:
    return "".join(lazy_pinyin(text))


class Matcher:
    def __init__(self, commands: tuple[Command, ...], cooldown: float = 2.0):
        self._cooldown = cooldown
        # [(pinyin_phrase, action)]
        self._patterns = [
            (_pin(p), c.action) for c in commands for p in c.phrases
        ]
        self._fired_this_utterance: set[str] = set()
        self._last_fired: dict[str, float] = {}

    def feed(self, text: str, now: float) -> str | None:
        """吃一段 partial 文字，回傳觸發的 action 或 None。"""
        hay = _pin(text)
        for pat, action in self._patterns:
            if action in self._fired_this_utterance:
                continue
            if now - self._last_fired.get(action, float("-inf")) < self._cooldown:
                continue
            if pat and pat in hay:
                self._fired_this_utterance.add(action)
                self._last_fired[action] = now
                return action
        return None

    def reset_utterance(self) -> None:
        """ASR endpoint（句子結束）時呼叫。"""
        self._fired_this_utterance.clear()
