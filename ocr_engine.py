"""识别引擎抽象层与内置引擎实现（Apple OCR 与本地视觉模型图像描述），技术选型与推荐模型见 README。

新增引擎时：继承 OCREngine 并在 OCR_ENGINES 注册表登记即可，
识别面板的引擎列表、Option+Shift+Q 循环切换与 ocr_mode 配置会自动生效。
"""

from __future__ import annotations

import base64
import logging
import os
import sys
import tempfile
import threading
from typing import Optional, Tuple

import setting

logger = logging.getLogger(__name__)


IS_MACOS = sys.platform == "darwin"

# pyobjc 框架绑定按平台守卫导入：缺失时 Apple OCR 降级为不可用，模块仍可导入与测试
NSPasteboard = None
NSURL = None
VNImageRequestHandler = None
VNRecognizeTextRequest = None
VNRequestTextRecognitionLevelAccurate = None

if IS_MACOS:
    try:
        from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep, NSPasteboard
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

# ImageIO（CGImageSource）绑定随 pyobjc 全家桶提供：仅供 VLM 引擎读取图片尺寸与大图降采样，
# 不可用时 VLM 直接用原图识别，不影响 Apple OCR
CGImageSourceCreateWithURL = None
CGImageSourceCopyPropertiesAtIndex = None
CGImageSourceCreateThumbnailAtIndex = None
kCGImageSourceCreateThumbnailFromImageAlways = None
kCGImageSourceCreateThumbnailWithTransform = None
kCGImageSourceThumbnailMaxPixelSize = None

if IS_MACOS:
    try:
        from Quartz import (
            CGImageSourceCreateWithURL,
            CGImageSourceCopyPropertiesAtIndex,
            CGImageSourceCreateThumbnailAtIndex,
            kCGImageSourceCreateThumbnailFromImageAlways,
            kCGImageSourceCreateThumbnailWithTransform,
            kCGImageSourceThumbnailMaxPixelSize,
        )
    except ImportError as exc:
        logger.warning(f"Quartz 绑定导入失败，视觉模型大图降采样不可用: {exc}")
        CGImageSourceCreateWithURL = None
        CGImageSourceCopyPropertiesAtIndex = None
        CGImageSourceCreateThumbnailAtIndex = None
        kCGImageSourceCreateThumbnailFromImageAlways = None
        kCGImageSourceCreateThumbnailWithTransform = None
        kCGImageSourceThumbnailMaxPixelSize = None

# llama_cpp 多模态按存在性守卫导入：通用 MTMDChatHandler 需 llama-cpp-python ≥ 0.3.26（支持 Qwen3-VL 等）
Llama = None
_LLAMA_VL_HANDLER = None
try:
    from llama_cpp import Llama
    from llama_cpp import llama_chat_format
    _LLAMA_VL_HANDLER = getattr(llama_chat_format, "MTMDChatHandler", None)
except ImportError:
    Llama = None
    _LLAMA_VL_HANDLER = None


class OCRError(RuntimeError):
    """Raised when an OCR engine cannot complete a request."""


class OCREngine:
    """OCR 引擎抽象基类：recognize 为同步阻塞调用，调用方负责放入后台线程"""

    # 配置存储键（config.json 的 ocr_mode）
    key: str = ""
    # 引擎显示名的 gettext 键
    display_key: str = ""

    def __init__(self, **config):
        # create_engine 统一注入配置项，引擎按需取用，未知项忽略
        self.config = dict(config)

    def configure(self, **config):
        """运行时更新引擎配置（默认仅记录，引擎按需覆盖）"""
        self.config.update(config)

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


# 视觉模型识别的图片面积上限：对齐 llama.cpp 对 Qwen-VL 系列的 1024×1024 输入封顶，
# 避免视觉编码计算缓冲区随像素数瞬时膨胀（大截图可达数 GB），16GB 统一内存机器尤为关键
VLM_IMAGE_MAX_PIXELS = 1024 * 1024


def downscale_target_dimensions(width: int, height: int, max_pixels: int = VLM_IMAGE_MAX_PIXELS) -> Optional[Tuple[int, int]]:
    """计算超限图片降采样后的目标尺寸；面积未超上限返回 None（原图直通）

    按面积等比缩放并保持纵横比；Qwen-VL 约每 28×28 像素一个视觉 token，
    封顶后 token 数与编码缓冲区均为可预期范围
    """
    if width <= 0 or height <= 0 or width * height <= max_pixels:
        return None
    scale = (max_pixels / (width * height)) ** 0.5
    return max(1, round(width * scale)), max(1, round(height * scale))


def _probe_image_size(image_path: str) -> Optional[Tuple[int, int]]:
    """读取图片像素尺寸（仅读文件头元数据，不解码位图）"""
    if not (CGImageSourceCreateWithURL and CGImageSourceCopyPropertiesAtIndex):
        return None
    try:
        url = NSURL.fileURLWithPath_(image_path)
        source = CGImageSourceCreateWithURL(url, None)
        if source is None:
            return None
        props = CGImageSourceCopyPropertiesAtIndex(source, 0, None)
        width = props and int(props["PixelWidth"])
        height = props and int(props["PixelHeight"])
        if not width or not height:
            return None
        return width, height
    except Exception as exc:
        logger.warning(f"读取图片尺寸失败: {exc}")
        return None


def _write_downscaled_image(image_path: str, target: Tuple[int, int]) -> Optional[str]:
    """将图片按目标尺寸解码缩放后写为 PNG 临时文件；失败返回 None（调用方回退原图识别）"""
    if not (CGImageSourceCreateWithURL and CGImageSourceCreateThumbnailAtIndex and NSBitmapImageRep):
        return None
    temp_path = ""
    try:
        url = NSURL.fileURLWithPath_(image_path)
        source = CGImageSourceCreateWithURL(url, None)
        if source is None:
            return None
        # 缩放在解码阶段同步完成（thumbnail 接口），不产生全尺寸位图的内存峰值
        cgimage = CGImageSourceCreateThumbnailAtIndex(source, 0, {
            kCGImageSourceCreateThumbnailFromImageAlways: True,
            kCGImageSourceCreateThumbnailWithTransform: True,  # 遵循 EXIF 方向
            kCGImageSourceThumbnailMaxPixelSize: float(max(target)),
        })
        if cgimage is None:
            return None
        rep = NSBitmapImageRep.alloc().initWithCGImage_(cgimage)
        png_data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
        if png_data is None:
            return None
        fd, temp_path = tempfile.mkstemp(suffix=".png", prefix="magic_ocr_scaled_")
        os.close(fd)
        if not png_data.writeToFile_atomically_(temp_path, True):
            raise OSError(f"写入失败：{temp_path}")
        return temp_path
    except Exception as exc:
        logger.warning(f"图片降采样失败: {exc}")
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return None


class LocalVLMEngine(OCREngine):
    """本地视觉语言模型图像描述引擎：llama_cpp 加载 GGUF 多模态模型，输出约 100 字简短图片描述

    推荐模型与下载方式见 README；经通用 MTMDChatHandler 加载（需 llama-cpp-python ≥ 0.3.26）。
    模型仅在首次识别/预加载时加载，实例可跨引擎切换复用（MainFrame 缓存）。
    面积超过 VLM_IMAGE_MAX_PIXELS 的大图先降采样再识别（Apple OCR 不做预处理，原图直通）。
    """

    key = "vlm"
    display_key = "ocr_engine_vlm"

    # 图像描述指令：面向视障用户，控制篇幅约 100 字并要求覆盖场景/主体/细节
    DESCRIBE_PROMPT = "请用大约100字简短描述这张图片：说明场景、主体与重要细节，不要输出任何解释或多余内容。"
    IMAGE_MIME = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp",
        ".gif": "image/gif", ".webp": "image/webp", ".heic": "image/heic",
    }
    # 100 字中文约 200 token，留冗余避免截断
    MAX_OUTPUT_TOKENS = 512

    def __init__(self, **config):
        super().__init__(**config)
        self.model_path = ""
        self.mmproj_path = ""
        self._llm = None
        self._load_lock = threading.Lock()
        self.configure(config.get("model_path", ""), config.get("mmproj_path", ""))

    def configure(self, model_path: str = "", mmproj_path: str = ""):
        """更新模型路径；路径变化时卸载已加载模型，下次识别/预加载重新加载"""
        if model_path != self.model_path or mmproj_path != self.mmproj_path:
            self.model_path = model_path or ""
            self.mmproj_path = mmproj_path or ""
            self.unload()

    def is_configured(self) -> bool:
        return bool(self.model_path) and bool(self.mmproj_path)

    def is_loaded(self) -> bool:
        return self._llm is not None

    def needs_load(self) -> bool:
        """模型已配置但尚未加载（供调用方在首次识别前给出加载提示）"""
        return self.is_configured() and self._llm is None

    def is_available_for(self, is_internal: bool) -> bool:
        # 与本地翻译 LLM 定位一致：面向公开版开放；DEBUG_BUILD 下由 available_engines 统一放开
        return not is_internal

    def is_available(self) -> bool:
        return self.is_configured() and Llama is not None and _LLAMA_VL_HANDLER is not None

    def get_status_message(self) -> str:
        if not self.is_configured():
            return "请先在设置面板选择视觉模型与视觉编码器文件"
        if Llama is None or _LLAMA_VL_HANDLER is None:
            return "本地视觉模型需要新版本 llama-cpp-python，请升级后使用"
        return "本地视觉模型已就绪"

    def load_model(self):
        """同步加载模型（阻塞，调用方需放入后台线程）；已加载时直接返回"""
        with self._load_lock:
            if self._llm is not None:
                return
            if not self.is_configured():
                raise OCRError(setting._("ocr_vlm_not_configured"))
            if Llama is None or _LLAMA_VL_HANDLER is None:
                raise OCRError(setting._("ocr_vlm_unavailable"))
            for label, path in (("视觉模型", self.model_path), ("视觉编码器", self.mmproj_path)):
                if not os.path.isfile(path):
                    raise OCRError(f"{label}文件不存在：{path}")
            try:
                chat_handler = _LLAMA_VL_HANDLER(clip_model_path=self.mmproj_path)
                self._llm = Llama(
                    model_path=self.model_path,
                    chat_handler=chat_handler,
                    n_ctx=4096,        # 需容纳图像 embedding
                    n_gpu_layers=-1,   # macOS Metal 全量 GPU
                    verbose=False,
                )
            except OCRError:
                raise
            except Exception as exc:
                self._llm = None
                raise OCRError(f"视觉模型加载失败：{exc}") from exc

    def unload(self):
        """卸载模型释放内存"""
        self._llm = None

    def _downscale_if_needed(self, image_path: str) -> Tuple[str, bool]:
        """图片面积超上限时先降采样再识别，否则原图直通（仅 VLM 引擎使用）

        返回（识别用路径, 是否生成了临时文件）；降采样失败回退原图，不阻断识别
        """
        size = _probe_image_size(image_path)
        target = downscale_target_dimensions(*size) if size else None
        if target is None:
            return image_path, False
        scaled_path = _write_downscaled_image(image_path, target)
        if scaled_path is None:
            return image_path, False
        return scaled_path, True

    def recognize(self, image_path: str) -> str:
        if not image_path or not os.path.isfile(image_path):
            raise OCRError(f"图片文件不存在：{image_path}")
        # 未加载时在此处同步加载：与预加载共用 _load_lock，加载中触发的识别会排队等待
        self.load_model()

        source_path, is_scaled_temp = self._downscale_if_needed(image_path)
        try:
            with open(source_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("ascii")
            ext = os.path.splitext(source_path)[1].lower()
            mime = self.IMAGE_MIME.get(ext, "image/png")
            output = self._llm.create_chat_completion(
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        {"type": "text", "text": self.DESCRIBE_PROMPT},
                    ],
                }],
                max_tokens=self.MAX_OUTPUT_TOKENS,
                temperature=0.2,
            )
            text = (output.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            return text.strip()
        except OCRError:
            raise
        except Exception as exc:
            raise OCRError(f"本地视觉模型识别失败：{exc}") from exc
        finally:
            # 仅清理降采样产生的临时文件，原图/剪贴板临时文件归调用方管理
            if is_scaled_temp:
                try:
                    os.remove(source_path)
                except OSError:
                    pass


# 引擎注册表（key -> 引擎类）：新引擎在此登记后，UI 引擎列表、
# Option+Shift+Q 循环切换与 ocr_mode 配置自动生效
OCR_ENGINES = {
    AppleOCREngine.key: AppleOCREngine,
    LocalVLMEngine.key: LocalVLMEngine,
}


def available_engines(is_internal: bool) -> list:
    """按内部机/公开版可见性策略返回当前可用引擎（保持注册顺序）

    开发内部版本（setting.DEBUG_BUILD=True）放开内部机限制，开放全部已注册引擎。
    返回的是虚拟引擎列表：不要求引擎可用/已配置，仅供切换与展示。
    """
    if setting.DEBUG_BUILD:
        is_internal = False
    engines = [engine_cls() for engine_cls in OCR_ENGINES.values()]
    return [engine for engine in engines if engine.is_available_for(is_internal)]


def create_engine(key: str, **config) -> OCREngine:
    """按配置键创建引擎实例，未知键抛 OCRError"""
    engine_cls = OCR_ENGINES.get(key)
    if engine_cls is None:
        raise OCRError(f"未知的 OCR 引擎：{key}")
    return engine_cls(**config)


def engine_display(key: str) -> str:
    """引擎 key 对应的本地化显示名；未知 key 原样返回"""
    engine_cls = OCR_ENGINES.get(key)
    return setting._(engine_cls.display_key) if engine_cls else key


def next_engine_key(keys: list, current_key: str, step: int) -> str:
    """在虚拟引擎列表中循环切换：返回偏移 step 步后的引擎 key（越界回绕）"""
    if not keys:
        return current_key
    try:
        idx = keys.index(current_key)
    except ValueError:
        idx = 0
    return keys[(idx + step) % len(keys)]


# 访达 Cmd+C 复制文件时的剪贴板类型
FILE_URL_TYPE = "public.file-url"
# 位图数据类型（依序尝试，扩展名用于落盘临时文件）
IMAGE_DATA_TYPES = (
    ("public.png", ".png"),
    ("public.tiff", ".tiff"),
    ("public.jpeg", ".jpg"),
)


def extract_clipboard_image() -> Optional[Tuple[str, bool]]:
    """从系统剪贴板提取图片，返回 (图片路径, 是否临时文件)；未找到图片返回 None。

    优先取访达 Cmd+C 复制的文件路径（原图、无损），不做文件类型校验
    （由引擎识别并播报错误）；否则将浏览器/聊天工具复制的位图数据写入临时文件。
    NSPasteboard 非线程安全，必须在主线程调用。
    """
    if not IS_MACOS or NSPasteboard is None:
        return None
    pasteboard = NSPasteboard.generalPasteboard()

    # 1) 文件 URL：访达复制的文件（多选时取第一个）
    urls = pasteboard.readObjectsForClasses_options_([NSURL], None) or []
    for url in urls:
        if not url.isFileURL():
            continue
        path = url.path()
        if path:
            return str(path), False

    # 2) 位图数据：直接复制的图片内容，写入临时文件后再交给引擎
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
