import logging
import os
import platform
import subprocess
import setting

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AppleTranslator:
    """Apple Translation Framework 封装类
    
    使用 xcrun 运行翻译（需要构建 Swift 工具）
    """

    def __init__(self):
        self._tool_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "AppleTranslateTool-bin"
        )
        self._tool_available = self._check_tool_available()

    def _check_tool_available(self) -> bool:
        """检查翻译工具是否可用"""
        return os.path.exists(self._tool_path)
    
    def get_status_message(self) -> str:
        """获取状态消息"""
        system_ok = setting.supports_apple_translation()
        tool_ok = self._check_tool_available()
        
        if not system_ok:
            return "系统不支持，需要 macOS 14.4+"
        if not tool_ok:
            return "翻译工具未构建，请参考 AppleTranslateTool/README.md"
        return "就绪"

    def is_available(self) -> bool:
        """检查翻译器是否可用"""
        return self._tool_available and setting.supports_apple_translation()
    
    def get_readiness_message(self) -> str:
        """获取就绪状态的消息"""
        if not setting.supports_apple_translation():
            return "系统不支持，需要 macOS 14.4+"
        if not self._check_tool_available():
            return "翻译工具未构建，请参考 AppleTranslateTool/README.md"
        return "苹果翻译已就绪"

    def check_and_notify(self) -> tuple:
        """检查状态并返回 (可用状态, 消息)
        
        Returns:
            (True, "") - 可用
            (False, message) - 不可用原因
        """
        if not setting.supports_apple_translation():
            return (False, "系统不支持，需要 macOS 14.4+")
        
        if not self._tool_available:
            return (False, "请构建翻译工具后使用")
        
        return (True, "")

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """翻译文本
        
        Args:
            text: 待翻译文本
            source_lang: 源语言代码
            target_lang: 目标语言代码
            
        Returns:
            翻译结果
        """
        available, msg = self.check_and_notify()
        if not available:
            raise RuntimeError(msg)

        source_code = setting.APPLE_TRANSLATION_LANG_MAP.get(source_lang, source_lang)
        target_code = setting.APPLE_TRANSLATION_LANG_MAP.get(target_lang, target_lang)

        try:
            result = subprocess.run(
                [self._tool_path, source_code, target_code, text],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.warning(f"翻译失败: {result.stderr}")
                raise RuntimeError(f"翻译失败: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("翻译超时")
        except Exception as e:
            raise RuntimeError(f"翻译异常: {str(e)}")

    def prepare_translation(self, source_lang: str, target_lang: str) -> bool:
        """预下载语言包
        
        Args:
            source_lang: 源语言代码
            target_lang: 目标语言代码
            
        Returns:
            是否成功开始下载
        """
        if not self._tool_available:
            return False

        source_code = setting.APPLE_TRANSLATION_LANG_MAP.get(source_lang, source_lang)
        target_code = setting.APPLE_TRANSLATION_LANG_MAP.get(target_lang, target_lang)

        try:
            result = subprocess.run(
                [self._tool_path, "--prepare", source_code, target_code],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_supported_languages(self) -> list:
        """获取支持的语言列表"""
        return list(setting.APPLE_TRANSLATION_LANG_MAP.keys())