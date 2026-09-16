"""OCR 引擎抽象层与 Apple 系统内置 OCR 实现。

Apple OCR 通过 pyobjc 直接调用 macOS Vision 框架（VNRecognizeTextRequest），
与 Apple 翻译（必须经 Swift 无头 CLI）不同：Vision 是标准 ObjC API，
pyobjc==12.1 全量包自带 Vision 绑定，无需构建额外的 Swift 工具。

新增第三方 OCR 引擎时：继承 OCREngine 并在 OCR_ENGINES 注册表登记即可，
识别面板的引擎列表与 ocr_mode 配置会自动生效。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from typing import Optional, Tuple

import setting

logger = logging.getLogger(__name__)


IS_MACOS = sys.platform == "darwin"

# pyobjc 框架绑定按平台守卫导入：缺失时引擎降级为不可用，模块仍可导入与测试
NSPasteboard = None
NSURL = None
VNImageRequestHandler = None
VNRecognizeTextRequest = None
VNRequestTextRecognitionLevelAccurate = None

if IS_MACOS:
    try:
        from AppKit import NSPasteboard
        from Foundation import NSURL
        from Vision import (
            VNImageRequestHandler,
            VNRecognizeTextRequest,
            VNRequestTextRecognitionLevelAccurate,
        )
    except ImportError as exc:
        logger.warning(f"Vision/AppKit 绑定导入失败，Apple OCR 不可用: {exc}")
        NSPasteboard = None
        NSURL = None
        VNImageRequestHandler = None
        VNRecognizeTextRequest = None
        VNRequestTextRecognitionLevelAccurate = None


class OCRError(RuntimeError):
    """Raised when an OCR engine cannot complete a request."""


class OCREngine:
    """OCR 引擎抽象基类：recognize 为同步阻塞调用，调用方负责放入后台线程"""

    # 配置存储键（config.json 的 ocr_mode）
    key: str = ""
    # 引擎显示名的 gettext 键
    display_key: str = ""

    def is_available_for(self, is_internal: bool) -> bool:
        """内部机/公开版可见性策略，默认对所有环境开放"""
        return True

    def is_available(self) -> bool:
        raise NotImplementedError

    def get_status_message(self) -> str:
        raise NotImplementedError

    def recognize(self, image_path: str) -> str:
        raise NotImplementedError


class AppleOCREngine(OCREngine):
    """Apple 系统内置 OCR：pyobjc 直调 Vision 框架"""

    key = "apple"
    display_key = "ocr_engine_apple"

    # 识别语言优先级（Vision 自动在候选语言中逐行挑选最佳匹配）
    RECOGNITION_LANGUAGES = ["zh-Hans", "zh-Hant", "en-US"]

    def is_available(self) -> bool:
        return (
            IS_MACOS
            and VNImageRequestHandler is not None
            and setting.supports_apple_translation()
        )

    def get_status_message(self) -> str:
        if not IS_MACOS or VNImageRequestHandler is None:
            return "未找到 Vision OCR（需要 macOS 与 pyobjc Vision 绑定）"
        if not setting.supports_apple_translation():
            return "系统不支持，需要 macOS 26.0 或更高版本"
        return "Apple OCR 已就绪"

    def recognize(self, image_path: str) -> str:
        if not self.is_available():
            raise OCRError(self.get_status_message())
        if not image_path or not os.path.isfile(image_path):
            raise OCRError(f"图片文件不存在：{image_path}")

        try:
            url = NSURL.fileURLWithPath_(image_path)
            handler = VNImageRequestHandler.alloc().initWithURL_options_(url, None)
            request = VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(VNRequestTextRecognitionLevelAccurate)
            request.setUsesLanguageCorrection_(True)
            request.setRecognitionLanguages_(list(self.RECOGNITION_LANGUAGES))

            ok, error = handler.performRequests_error_([request], None)
            if not ok:
                detail = error.localizedDescription() if error else "未知错误"
                raise OCRError(f"Vision 识别失败：{detail}")
            return self._collect_lines(request)
        except OCRError:
            raise
        except Exception as exc:
            raise OCRError(f"Vision 识别失败：{exc}") from exc

    @staticmethod
    def _collect_lines(request) -> str:
        """按行收集识别结果，行序即版面阅读顺序"""
        lines = []
        for observation in (request.results() or []):
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))
        return "\n".join(lines)


# 引擎注册表：第三方 OCR 引擎选定后在此登记（key -> 引擎类），
# available_engines / create_engine 与识别面板 UI、ocr_mode 配置随之自动生效
OCR_ENGINES = {
    AppleOCREngine.key: AppleOCREngine,
}


def available_engines(is_internal: bool) -> list:
    """按内部机/公开版可见性策略返回当前可用引擎（保持注册顺序）"""
    engines = [engine_cls() for engine_cls in OCR_ENGINES.values()]
    return [engine for engine in engines if engine.is_available_for(is_internal)]


def create_engine(key: str) -> OCREngine:
    """按配置键创建引擎实例，未知键抛 OCRError"""
    engine_cls = OCR_ENGINES.get(key)
    if engine_cls is None:
        raise OCRError(f"未知的 OCR 引擎：{key}")
    return engine_cls()


# 访达 Cmd+C 复制文件时的剪贴板类型
FILE_URL_TYPE = "public.file-url"
# 位图数据类型（依序尝试，扩展名用于落盘临时文件）
IMAGE_DATA_TYPES = (
    ("public.png", ".png"),
    ("public.tiff", ".tiff"),
    ("public.jpeg", ".jpg"),
)

# 允许直接交给 Vision 的图片扩展名白名单
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".bmp", ".gif", ".webp",
}


def extract_clipboard_image() -> Optional[Tuple[str, bool]]:
    """从系统剪贴板提取图片，返回 (图片路径, 是否临时文件)；未找到图片返回 None。

    优先取访达 Cmd+C 复制的图片文件路径（原图、无损），
    否则将浏览器/聊天工具复制的位图数据写入临时文件。
    NSPasteboard 非线程安全，必须在主线程调用。
    """
    if not IS_MACOS or NSPasteboard is None:
        return None
    pasteboard = NSPasteboard.generalPasteboard()

    # 1) 文件 URL：访达复制的文件（多选时逐个检查，取第一个图片文件）
    urls = pasteboard.readObjectsForClasses_options_([NSURL], None) or []
    for url in urls:
        if not url.isFileURL():
            continue
        path = url.path()
        if not path:
            continue
        path = str(path)
        if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS and os.path.isfile(path):
            return path, False

    # 2) 位图数据：直接复制的图片内容，写入临时文件后再交给 Vision
    for utype, ext in IMAGE_DATA_TYPES:
        data = pasteboard.dataForType_(utype)
        if data:
            return _write_temp_image(data, ext), True

    return None


def _write_temp_image(data, ext: str) -> str:
    """将剪贴板位图数据（NSData）写入临时文件，调用方用毕负责删除"""
    fd, temp_path = tempfile.mkstemp(suffix=ext, prefix="magic_ocr_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(bytes(data))
    except Exception:
        # 落盘失败时清理半成品文件，异常继续抛给调用方播报
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    return temp_path
