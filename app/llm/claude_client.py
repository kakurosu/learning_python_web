"""Thin wrapper around the Anthropic SDK for the "more details" feature.

When ``ANTHROPIC_API_KEY`` is not set, the client reports ``available=False``
and the UI hides any LLM-driven buttons.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5"
SYSTEM_PROMPT = (
    "あなたは Python 学習者を励ます棒人間のメンターです。"
    "ユーザーは提出したコードへのフィードバックを求めています。"
    "次の制約に厳密に従ってください:\n"
    "1) 答えそのものを書かないこと（学習機会を奪う）。\n"
    "2) 200 字以内、敬体（です・ます）。\n"
    "3) 段階的なヒントを 1 段階だけ示すこと。\n"
    "4) 絵文字は使わない。\n"
)


@dataclass
class HintRequest:
    chapter_title: str
    learning_goals: list[str]
    page_title: str
    prompt: str
    submitted_code: str
    stdout: str
    stderr: str
    passed: bool


class ClaudeClient:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.model = model
        self._client: Any = None
        self._cache: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            import anthropic
        except ImportError:
            log.warning("anthropic SDK not installed")
            self._client = None
            self.api_key = ""
            return
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def request_more_details(self, req: HintRequest) -> str:
        """Synchronously request a Claude hint. Returns plain text or an error string."""
        if not self.available:
            return "Claude API キーが設定されていません。.env に ANTHROPIC_API_KEY を追加してください。"

        cache_key = f"{req.chapter_title}/{req.page_title}/{hash(req.submitted_code)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        self._ensure_client()
        if self._client is None:
            return "anthropic パッケージが見つかりません。`pip install anthropic` で導入してください。"

        user_msg = (
            f"章: {req.chapter_title}\n"
            f"到達目標: {', '.join(req.learning_goals)}\n"
            f"ページ: {req.page_title}\n"
            f"問題文: {req.prompt}\n"
            f"---\n"
            f"提出されたコード:\n```python\n{req.submitted_code}\n```\n"
            f"標準出力: {req.stdout!r}\n"
            f"エラー出力: {req.stderr!r}\n"
            f"判定: {'正解' if req.passed else '不正解'}\n"
            "コードの考え方について 200 字以内でひと言フィードバックをください。"
            "不正解なら段階的ヒント、正解なら次のステップの示唆を。"
        )
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            text_parts = [
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            ]
            text = "\n".join(text_parts).strip()
            if not text:
                text = "（応答が空でした）"
            self._cache[cache_key] = text
            return text
        except Exception as e:  # noqa: BLE001
            log.exception("Claude API call failed")
            return f"Claude API 呼び出しに失敗しました: {e}"
