"""Python bridge for Apple's on-device Translation framework."""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
from typing import Any

import setting

logger = logging.getLogger(__name__)


TOOL_RELATIVE_PATH = os.path.join(
    "AppleTranslateTool.app", "Contents", "MacOS", "AppleTranslateTool-bin"
)


class AppleTranslationError(RuntimeError):
    """Raised when the native Apple Translation helper cannot complete a request."""


class AppleTranslator:
    """Invoke the bundled SwiftUI helper over a small JSON/stdin protocol."""

    DEFAULT_TIMEOUT = 300

    def __init__(self, tool_path: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        self._tool_path = tool_path
        self._timeout = timeout

    @staticmethod
    def _candidate_roots() -> list[str]:
        """按优先级返回翻译工具可能所在的根目录（源码目录与打包后的 bundle 内部）"""
        roots = [os.path.dirname(os.path.abspath(__file__))]
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                roots.append(meipass)
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            roots.append(exe_dir)
            roots.append(os.path.normpath(os.path.join(exe_dir, os.pardir, "Resources")))
        return roots

    def _resolve_tool_path(self) -> str | None:
        """惰性解析工具路径：显式指定优先，其次依次查找各候选目录"""
        if self._tool_path:
            return self._tool_path if os.path.isfile(self._tool_path) else None
        for root in self._candidate_roots():
            candidate = os.path.join(root, TOOL_RELATIVE_PATH)
            if os.path.isfile(candidate):
                return candidate
        return None

    def _check_tool_available(self) -> bool:
        tool_path = self._resolve_tool_path()
        if not tool_path:
            return False
        if os.name == "posix":
            return bool(os.stat(tool_path).st_mode & stat.S_IXUSR)
        return True

    def get_status_message(self) -> str:
        if not setting.supports_apple_translation():
            return "系统不支持，需要 macOS 15.0 或更高版本"
        if not self._check_tool_available():
            return "翻译工具未构建，请运行 build_apple_translator.sh"
        return "Apple 翻译已就绪"

    get_readiness_message = get_status_message

    def is_available(self) -> bool:
        return setting.supports_apple_translation() and self._check_tool_available()

    def check_and_notify(self) -> tuple[bool, str]:
        if not setting.supports_apple_translation():
            return False, "系统不支持，需要 macOS 15.0 或更高版本"
        if not self._check_tool_available():
            return False, "请先运行 build_apple_translator.sh 构建翻译工具"
        return True, ""

    def _invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        available, message = self.check_and_notify()
        if not available:
            raise AppleTranslationError(message)
        tool_path = self._resolve_tool_path()
        if not tool_path:
            raise AppleTranslationError("未找到 Apple 翻译工具")

        try:
            result = subprocess.run(
                [tool_path],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppleTranslationError("Apple 翻译超时") from exc
        except OSError as exc:
            raise AppleTranslationError(f"无法启动 Apple 翻译工具：{exc}") from exc

        stdout = result.stdout.strip()
        try:
            reply = json.loads(stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            detail = result.stderr.strip() or stdout or f"exit code {result.returncode}"
            raise AppleTranslationError(f"Apple 翻译工具返回了无效响应：{detail}") from exc

        if result.returncode != 0 or not reply.get("ok"):
            detail = reply.get("error") or result.stderr.strip() or "未知错误"
            raise AppleTranslationError(f"Apple 翻译失败：{detail}")
        return reply

    @staticmethod
    def _language_code(language: str) -> str:
        return setting.APPLE_TRANSLATION_LANG_MAP.get(language, language)

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not isinstance(text, str) or not text.strip():
            return ""
        reply = self._invoke({
            "action": "translate",
            "sourceLanguage": self._language_code(source_lang),
            "targetLanguage": self._language_code(target_lang),
            "text": text,
        })
        translated = reply.get("translatedText")
        if not isinstance(translated, str):
            raise AppleTranslationError("Apple 翻译工具未返回译文")
        return translated

    def prepare_translation(self, source_lang: str, target_lang: str) -> bool:
        self._invoke({
            "action": "prepare",
            "sourceLanguage": self._language_code(source_lang),
            "targetLanguage": self._language_code(target_lang),
        })
        return True

    def get_supported_languages(self) -> list[str]:
        return list(setting.APPLE_TRANSLATION_LANG_MAP)
