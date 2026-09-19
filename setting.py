import base64
import gettext
import hashlib
import json
import logging
import os
import plistlib
import subprocess

from cryptography.fernet import Fernet


# 应用数据目录（各配置文件均存放于此）
app_support_dir = os.path.expanduser("~/Library/Application Support/")
app_data_dir = os.path.join(app_support_dir, "MagicToolbox")
os.makedirs(app_data_dir, exist_ok=True)
config_path = os.path.join(app_data_dir, "config.json")


def _load_debug_build() -> bool:
    """从应用数据目录的 debug_config.json 读取开发内部版本标志

    本机开发测试时写入 {"debug_build": true} 并重启应用即可放开限制，
    文件缺失、解析失败或值为 false 时默认关闭，正式发布无需改动代码。
    """
    path = os.path.join(app_data_dir, "debug_config.json")
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                value = json.load(f).get('debug_build', False)
                if isinstance(value, str):
                    # 手写配置常见把 false 写成字符串：bool("false") 为真会静默放开内部机限制，
                    # 只认明确的真值写法
                    return value.strip().lower() in ("true", "1", "yes")
                return bool(value)
    except Exception as e:
        logging.warning(f"加载调试配置失败: {e}")
    return False


# 开发内部版本标志：True 时放开"内部机只开放 Apple"限制，开放全部引擎/翻译模式
DEBUG_BUILD = _load_debug_build()


def _get_fernet():
    result = subprocess.run(
        ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
        capture_output=True, text=True
    )
    for line in result.stdout.split('\n'):
        if 'IOPlatformUUID' in line:
            machine_id = line.split('"')[-2] + '@Asher'
            key = hashlib.sha256(machine_id.encode()).digest()
            key_b64 = base64.urlsafe_b64encode(key)
            return Fernet(key_b64)
    raise Exception("无法获取机器UUID")


_fernet = _get_fernet()


_current_dir = os.path.dirname(os.path.abspath(__file__))
_locale_dir = os.path.join(_current_dir, "locales")


def _get_system_locale():
    """通过读取系统plist文件获取macOS语言设置"""
    try:
        plist_path = os.path.expanduser("~/Library/Preferences/.GlobalPreferences.plist")
        with open(plist_path, 'rb') as f:
            plist_data = plistlib.load(f)
        apple_languages = plist_data.get('AppleLanguages', [])
        if not apple_languages:
            return 'en'
        primary_lang = apple_languages[0]
        if primary_lang.startswith('zh'):
            return 'zh_CN'
        else:
            return 'en'
    except Exception:
        return 'en'


_locale = _get_system_locale()
try:
    _trans = gettext.translation('messages', localedir=_locale_dir, languages=[_locale])
except FileNotFoundError:
    _trans = gettext.NullTranslations()


def _(s):
    """翻译函数"""
    return _trans.gettext(s)


current_lang = 'zh' if _locale.startswith('zh') else 'en'


#  字符集合
chars_dict = {
    'zh': {
        ' ': '空格',
        '\n': '换行',
        '	': '制表符',
        '#': '井号',
        '/': '斜线',
        '\\': '反斜线',
        '[': '左中括号',
        ']': '右中括号',
        '［': '全角左中括号',
        '］': '全角右中括号',
        '"': '双引号',
        '“': '左双引号',
        '”': '右双引号',
        "'": '单引号',
        '‘': '左单引号',
        '’': '右单引号',
        '，': '全角逗号',
        '。': '句号',
        '？': '全角问号',
        '！': '全角感叹号',
        '：': '全角冒号',
        '；': '全角分号',
        '.': '句点',
        ',': '逗号',
        ':': '冒号',
        ';': '分号',
        '?': '问号',
        '!': '感叹号',
        '(': '左圆括号',
        ')': '右圆括号',
        '{': '左大括号',
        '}': '右大括号',
        '<': '小于号',
        '>': '大于号',
        '-': '连字符',
        '_': '下划线',
        '=': '等号',
        '+': '加号',
        '*': '星号',
        '&': '与符号',
        '%': '百分号',
        '$': '美元符号',
        '@': '艾特符号',
        '|': '竖线',
        '~': '波浪号',
        '^': '脱字符',
        '`': '反引号',
        '、': '顿号',
        '（': '全角左圆括号',
        '）': '全角右圆括号',
        '《': '左书名号',
        '》': '右书名号',
        '【': '左方头括号',
        '】': '右方头括号',
        '·': '间隔号',
        '—': '破折号',
        '…': '省略号',
        '～': '全角波浪号',
        '￥': '人民币符号',
        'ā': '一声阿',
        'á': '二声嗄',
        'ǎ': '三声啊',
        'à': '四声啊',
        'ō': '一声噢',
        'ó': '二声哦',
        'ǒ': '三声呕',
        'ò': '四声怄',
        'ē': '一声婀',
        'é': '二声鹅',
        'ě': '三声恶',
        'è': '四声饿',
        'ī': '一声衣',
        'í': '二声姨',
        'ǐ': '三声已',
        'ì': '四声亿',
        'ū': '一声屋',
        'ú': '二声吴',
        'ǔ': '三声五',
        'ù': '四声务',
        'ǖ': '一声淤',
        'ǘ': '二声鱼',
        'ǚ': '三声雨',
        'ǜ': '四声欲',
        'ㄅ': '注音符號,八聲,B3',
        'ㄆ': '注音符號,匹聲,P1',
        'ㄇ': '注音符號,罵聲,M1',
        'ㄈ': '注音符號,芳聲,F2',
        'ㄉ': '注音符號,刀聲,D',
        'ㄊ': '注音符號,他聲,T',
        'ㄋ': '注音符號,鳥聲,N1',
        'ㄌ': '注音符號,拉聲,L2',
        'ㄍ': '注音符號,哥聲,G1',
        'ㄎ': '注音符號,客聲,K2',
        'ㄏ': '注音符號,喝聲,H',
        'ㄐ': '注音符號,機聲,J1',
        'ㄑ': '注音符號,氣聲,CI',
        'ㄒ': '注音符號,西聲,X',
        'ㄓ': '注音符號,知聲,J2',
        'ㄔ': '注音符號,吃聲,CH',
        'ㄕ': '注音符號,詩聲,SH',
        'ㄖ': '注音符號,日聲,R2',
        'ㄗ': '注音符號,姿聲,Z',
        'ㄘ': '注音符號,疵聲,C2',
        'ㄙ': '注音符號,思聲,S2',
        'ㄧ': '注音符號,一聲,I',
        'ㄨ': '注音符號,烏聲,W2',
        'ㄩ': '注音符號,迂聲,U1',
        'ㄚ': '注音符號,阿聲,A1',
        'ㄛ': '注音符號,喔聲,O3',
        'ㄜ': '注音符號,婀聲,E3',
        'ㄝ': '注音符號,葉聲,E2',
        'ㄞ': '注音符號,埃聲,AI',
        'ㄟ': '注音符號,威聲,EI',
        'ㄠ': '注音符號,凹聲,AU',
        'ㄡ': '注音符號,歐聲,OU',
        'ㄢ': '注音符號,安聲,AN',
        'ㄣ': '注音符號,恩聲,EN',
        'ㄤ': '注音符號,骯聲,ANG',
        'ㄥ': '注音符號,英聲,ENG',
        'ㄦ': '注音符號,兒聲,R3',
        'Ⅰ': '羅馬數字一',
        'Ⅱ': '羅馬數字二',
        'Ⅲ': '羅馬數字三',
        'Ⅳ': '羅馬數字四',
        'Ⅴ': '羅馬數字五',
        'Ⅵ': '羅馬數字六',
        'Ⅶ': '羅馬數字七',
        'Ⅷ': '羅馬數字八',
        'Ⅸ': '羅馬數字九',
        'Ⅹ': '羅馬數字十'
    },
    'en': {
        ' ': 'space',
        '\n': 'new line',
        '	': 'Tab',
        '#': 'Number',
        '/': 'slash',
        '\\': 'back slash',
        '[': 'left square bracket',
        ']': 'right square bracket',
        '［': 'full-width left square bracket',
        '］': 'full-width right square bracket',
        '"': 'half-width double quote',
        '“': 'full-width left double quote',
        '”': 'full-width right double quote',
        "'": 'half-width single quote',
        '‘': 'full-width left single quote',
        '’': 'full-width right single quote',
        '，': 'full-width comma',
        '。': 'full-width period',
        '？': 'full-width question mark',
        '！': 'full-width exclamation mark',
        '：': 'full-width colon',
        '；': 'full-width semicolon',
        '.': 'period',
        ',': 'comma',
        ':': 'colon',
        ';': 'semicolon',
        '?': 'question mark',
        '!': 'exclamation mark',
        '(': 'left parenthesis',
        ')': 'right parenthesis',
        '{': 'left brace',
        '}': 'right brace',
        '<': 'less than sign',
        '>': 'greater than sign',
        '-': 'hyphen',
        '_': 'underscore',
        '=': 'equals sign',
        '+': 'plus sign',
        '*': 'asterisk',
        '&': 'ampersand',
        '%': 'percent sign',
        '$': 'dollar sign',
        '@': 'at sign',
        '|': 'vertical bar',
        '~': 'tilde',
        '^': 'circumflex accent',
        '`': 'backtick',
        '、': 'enumeration comma',
        '（': 'full-width left parenthesis',
        '）': 'full-width right parenthesis',
        '《': 'left double angle bracket',
        '》': 'right double angle bracket',
        '【': 'left black lenticular bracket',
        '】': 'right black lenticular bracket',
        '·': 'middle dot',
        '—': 'em dash',
        '…': 'ellipsis',
        '～': 'full-width tilde',
        '￥': 'yen sign',
        'ā': 'first tone a',
        'á': 'second tone a',
        'ǎ': 'third tone a',
        'à': 'fourth tone a',
        'ō': 'first tone o',
        'ó': 'second tone o',
        'ǒ': 'third tone o',
        'ò': 'fourth tone o',
        'ē': 'first tone e',
        'é': 'second tone e',
        'ě': 'third tone e',
        'è': 'fourth tone e',
        'ī': 'first tone i',
        'í': 'second tone i',
        'ǐ': 'third tone i',
        'ì': 'fourth tone i',
        'ū': 'first tone u',
        'ú': 'second tone u',
        'ǔ': 'third tone u',
        'ù': 'fourth tone u',
        'ǖ': 'first tone ü',
        'ǘ': 'second tone ü',
        'ǚ': 'third tone ü',
        'ǜ': 'fourth tone ü',
        'ㄅ': 'bopomofo, ba sound, B3',
        'ㄆ': 'bopomofo, pi sound, P1',
        'ㄇ': 'bopomofo, ma sound, M1',
        'ㄈ': 'bopomofo, fang sound, F2',
        'ㄉ': 'bopomofo, dao sound, D',
        'ㄊ': 'bopomofo, ta sound, T',
        'ㄋ': 'bopomofo, niao sound, N1',
        'ㄌ': 'bopomofo, la sound, L2',
        'ㄍ': 'bopomofo, ge sound, G1',
        'ㄎ': 'bopomofo, ke sound, K2',
        'ㄏ': 'bopomofo, he sound, H',
        'ㄐ': 'bopomofo, ji sound, J1',
        'ㄑ': 'bopomofo, qi sound, CI',
        'ㄒ': 'bopomofo, xi sound, X',
        'ㄓ': 'bopomofo, zhi sound, J2',
        'ㄔ': 'bopomofo, chi sound, CH',
        'ㄕ': 'bopomofo, shi sound, SH',
        'ㄖ': 'bopomofo, ri sound, R2',
        'ㄗ': 'bopomofo, zi sound, Z',
        'ㄘ': 'bopomofo, ci sound, C2',
        'ㄙ': 'bopomofo, si sound, S2',
        'ㄧ': 'bopomofo, yi sound, I',
        'ㄨ': 'bopomofo, wu sound, W2',
        'ㄩ': 'bopomofo, yu sound, U1',
        'ㄚ': 'bopomofo, a sound, A1',
        'ㄛ': 'bopomofo, o sound, O3',
        'ㄜ': 'bopomofo, e sound, E3',
        'ㄝ': 'bopomofo, ye sound, E2',
        'ㄞ': 'bopomofo, ai sound, AI',
        'ㄟ': 'bopomofo, wei sound, EI',
        'ㄠ': 'bopomofo, ao sound, AU',
        'ㄡ': 'bopomofo, ou sound, OU',
        'ㄢ': 'bopomofo, an sound, AN',
        'ㄣ': 'bopomofo, en sound, EN',
        'ㄤ': 'bopomofo, ang sound, ANG',
        'ㄥ': 'bopomofo, ying sound, ENG',
        'ㄦ': 'bopomofo, er sound, R3',
        'Ⅰ': 'Roman numeral I',
        'Ⅱ': 'Roman numeral II',
        'Ⅲ': 'Roman numeral III',
        'Ⅳ': 'Roman numeral IV',
        'Ⅴ': 'Roman numeral V',
        'Ⅵ': 'Roman numeral VI',
        'Ⅶ': 'Roman numeral VII',
        'Ⅷ': 'Roman numeral VIII',
        'Ⅸ': 'Roman numeral IX',
        'Ⅹ': 'Roman numeral X'
    }
}


lang_code_to_trans = {
    'English': 'lang_English',
    'Chinese': 'lang_Chinese',
    'French': 'lang_French',
    'Portuguese': 'lang_Portuguese',
    'Spanish': 'lang_Spanish',
    'Japanese': 'lang_Japanese',
    'Turkish': 'lang_Turkish',
    'Russian': 'lang_Russian',
    'Arabic': 'lang_Arabic',
    'Korean': 'lang_Korean',
    'Thai': 'lang_Thai',
    'Italian': 'lang_Italian',
    'German': 'lang_German',
    'Vietnamese': 'lang_Vietnamese',
    'Malay': 'lang_Malay',
    'Indonesian': 'lang_Indonesian',
    'Filipino': 'lang_Filipino',
    'Hindi': 'lang_Hindi',
    'Traditional Chinese': 'lang_Traditional Chinese',
    'Polish': 'lang_Polish',
    'Czech': 'lang_Czech',
    'Dutch': 'lang_Dutch',
    'Khmer': 'lang_Khmer',
    'Burmese': 'lang_Burmese',
    'Persian': 'lang_Persian',
    'Gujarati': 'lang_Gujarati',
    'Urdu': 'lang_Urdu',
    'Telugu': 'lang_Telugu',
    'Marathi': 'lang_Marathi',
    'Hebrew': 'lang_Hebrew',
    'Bengali': 'lang_Bengali',
    'Tamil': 'lang_Tamil',
    'Ukrainian': 'lang_Ukrainian',
    'Tibetan': 'lang_Tibetan',
    'Kazakh': 'lang_Kazakh',
    'Mongolian': 'lang_Mongolian',
    'Uyghur': 'lang_Uyghur',
    'Cantonese': 'lang_Cantonese',
}


def get_lang_display(code: str) -> str:
    """获取语言代码对应的显示名称（通过gettext翻译）"""
    key = lang_code_to_trans.get(code, code)
    return _(key)


#快捷键定义
hotKeys = [
    {
        "name": "altc",
        "modifiers": ["ALT"],
        "key": "c",
        "handler": "on_hotkey_altc",
        "description": "Alt+c查字典"
    },
    {
        "name": "altd",
        "modifiers": ["ALT"],
        "key": "d",
        "handler": "on_hotkey_altd",
        "description": "Alt+D英译中"
    },
    {
        "name": "altshiftd",
        "modifiers": ["ALT", "SHIFT"],
        "key": "d",
        "handler": "on_hotkey_altshiftd",
        "description": "alt+shift+d中译英"
    },
    {
        "name": "altt",
        "modifiers": ["ALT"],
        "key": "t",
        "handler": "on_hotkey_altt",
        "description": "alt+T剪贴板编辑器"
    },
    {
        "name": "alta",
        "modifiers": ["ALT"],
        "key": "a",
        "handler": "on_hotkey_alta",
        "description": "alt+A列表第一项追加VO"
    },
    {
        "name": "a ltshift7",
        "modifiers": ["ALT", "SHIFT"],
        "key": "7",
        "handler": "on_hotkey_altshift7",
        "description": "alt+shift+7: 剪贴板列表上一条，长按跳到第一项"
    },
    {
        "name": "altshift8",
        "modifiers": ["ALT", "SHIFT"],
        "key": "8",
        "handler": "on_hotkey_altshift8",
        "description": "alt+shift+8: 当前剪贴板上一行，长按跳到第一行"
    },
    {
        "name": "altshift9",
        "modifiers": ["ALT", "SHIFT"],
        "key": "9",
        "handler": "on_hotkey_altshift9",
        "description": "alt+shift+9: 剪贴板列表下一条，长按跳到最后一条"
    },
    {
        "name": "altshiftu",
        "modifiers": ["ALT", "SHIFT"],
        "key": "u",
        "handler": "on_hotkey_altshiftu",
        "description": "alt+shift+u: 当前剪贴板前一个字"
    },
    {
        "name": "altshifti",
        "modifiers": ["ALT", "SHIFT"],
        "key": "i",
        "handler": "on_hotkey_altshifti",
        "description": "alt+shift+i: 当前字符解释"
    },
    {
        "name": "altshifto",
        "modifiers": ["ALT", "SHIFT"],
        "key": "o",
        "handler": "on_hotkey_altshifto",
        "description": "alt+shift+o: 当前剪贴板后一个字"
    },
    {
        "name": "altshiftj",
        "modifiers": ["ALT", "SHIFT"],
        "key": "j",
        "handler": "on_hotkey_altshiftj",
        "description": "alt+shift+j: 获取当前剪贴板到系统"
    },
    {
        "name": "altshiftk",
        "modifiers": ["ALT", "SHIFT"],
        "key": "k",
        "handler": "on_hotkey_altshiftk",
        "description": "alt+shift+k: 当前剪贴板下一行，长按跳到最后一行"
    },
    {
        "name": "altshiftm",
        "modifiers": ["ALT", "SHIFT"],
        "key": "m",
        "handler": "on_hotkey_altshiftm",
        "description": "alt+shift+m: 当前剪贴板字数统计"
    },
    {
        "name": "altshiftp",
        "modifiers": ["ALT", "SHIFT"],
        "key": "p",
        "handler": "on_hotkey_altshiftp",
        "description": "alt+shift+p: 粘贴剪贴板当前行"
    },
    {
        "name": "altshiftr",
        "modifiers": ["ALT", "SHIFT"],
        "key": "r",
        "handler": "on_hotkey_altshiftr",
        "description": "alt+shift+r: 按当前引擎识别剪贴板图片(OCR/图像描述)"
    },
    {
        "name": "altshiftq",
        "modifiers": ["ALT", "SHIFT"],
        "key": "q",
        "handler": "on_hotkey_altshiftq",
        "description": "alt+shift+q: 循环切换识别引擎"
    },
    {
        "name": "altshiftt",
        "modifiers": ["ALT", "SHIFT"],
        "key": "t",
        "handler": "on_hotkey_altshiftt",
        "description": "alt+shift+t: 循环切换翻译引擎"
    },
    {
        "name": "altshifte",
        "modifiers": ["ALT", "SHIFT"],
        "key": "e",
        "handler": "on_hotkey_altshifte",
        "description": "alt+shift+e: 提取VO最后朗读内容中的链接并用默认浏览器打开，多个时弹窗选择"
    }
]

# 鼠标路标槽位键：1-6 与 0；7/8/9 已被剪贴板导航占用，不得使用（菜单栏入口同用此定义）
MOUSE_LANDMARK_SLOTS = ("1", "2", "3", "4", "5", "6", "0")

# 鼠标路标热键：opt+shift+数字 标记当前鼠标位置，再加 cmd 跳转回标记点
for _digit in MOUSE_LANDMARK_SLOTS:
    hotKeys.append({
        "name": f"mark_{_digit}",
        "modifiers": ["ALT", "SHIFT"],
        "key": _digit,
        "handler": "on_hotkey_mouse_mark",
        "description": f"opt+shift+{_digit}: 标记当前鼠标位置为路标槽位{_digit}"
    })
    hotKeys.append({
        "name": f"jump_{_digit}",
        "modifiers": ["CMD", "ALT", "SHIFT"],
        "key": _digit,
        "handler": "on_hotkey_mouse_jump",
        "description": f"cmd+opt+shift+{_digit}: 跳转到路标槽位{_digit}的位置"
    })


# 文本编辑器分句功能的默认标点（原硬编码值，可在设置面板自定义）
DEFAULT_SENTENCE_PUNCTUATIONS = [',', '，', '.', '。', '!', '！', '?', '？', ';', '；', ':', '：', '"', '-']

# 当前生效的分句标点：启动加载配置时刷新，TextProcessor 分句时实时读取
sentence_punctuations = list(DEFAULT_SENTENCE_PUNCTUATIONS)

# 鼠标路标：按前台应用持久ID分组记录各数字槽位的屏幕坐标，格式 {app_id: {"1": [x, y], ...}}
mouse_landmarks = {}


def _normalize_sentence_punctuations(value) -> list:
    """清洗分句标点配置：仅保留单字符项，去空去重，非法输入回退默认值"""
    if not isinstance(value, list):
        return list(DEFAULT_SENTENCE_PUNCTUATIONS)
    result = []
    for item in value:
        symbol = str(item).strip() if item is not None else ''
        if len(symbol) == 1 and symbol not in result:
            result.append(symbol)
    return result if result else list(DEFAULT_SENTENCE_PUNCTUATIONS)


def _normalize_mouse_landmarks(value) -> dict:
    """清洗鼠标路标配置：仅保留 {app_id: {槽位: [x, y]}} 结构的合法项，非法整体丢弃"""
    if not isinstance(value, dict):
        return {}
    result = {}
    for app_id, slots in value.items():
        if not isinstance(slots, dict):
            continue
        clean_slots = {}
        for slot, pos in slots.items():
            # 坐标只接受列表/元组：字符串与字典下标取值会分别误收或抛 KeyError
            if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                continue
            try:
                x, y = float(pos[0]), float(pos[1])
            except (TypeError, ValueError):
                continue
            clean_slots[str(slot)] = [x, y]
        if clean_slots:
            result[str(app_id)] = clean_slots
    return result


def load_config():
    """加载配置"""
    global sentence_punctuations, mouse_landmarks
    config = {
        'source_lang': 'English',
        'target_lang': 'Chinese',
        'model_path': '',
        'clipboard_max_count': 1000,
        'volume_limit': 100,
        'volume_target': 80,
        'translation_mode': 'llm',
        'ocr_mode': 'apple',
        'ocr_model_path': '',
        'ocr_mmproj_path': '',
        'sentence_punctuations': list(DEFAULT_SENTENCE_PUNCTUATIONS),
        'mouse_landmarks': {}
    }
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                config.update(saved_config)
    except Exception as e:
        logging.warning(f"加载配置失败: {e}")
    sentence_punctuations = _normalize_sentence_punctuations(config.get('sentence_punctuations'))
    mouse_landmarks = _normalize_mouse_landmarks(config.get('mouse_landmarks'))
    return config


def save_config(source_lang: str, target_lang: str, model_path: str = '', clipboard_max_count: int = 1000, volume_limit: float = 100, volume_target: float = 80, translation_mode: str = 'llm', ocr_mode: str = 'apple', ocr_model_path: str = '', ocr_mmproj_path: str = '', sentence_punctuations=None, mouse_landmarks=None):
    """保存配置；sentence_punctuations 与 mouse_landmarks 未传入时保留当前生效值，避免其他配置项保存时覆盖"""
    if sentence_punctuations is None:
        sentence_punctuations = globals()['sentence_punctuations']
    normalized = _normalize_sentence_punctuations(sentence_punctuations)
    # 保存的同时同步模块级生效值（分句功能实时读取），保持配置与内存一致
    globals()['sentence_punctuations'] = normalized
    if mouse_landmarks is None:
        mouse_landmarks = globals()['mouse_landmarks']
    normalized_landmarks = _normalize_mouse_landmarks(mouse_landmarks)
    globals()['mouse_landmarks'] = normalized_landmarks
    try:
        config = {
            'source_lang': source_lang,
            'target_lang': target_lang,
            'model_path': model_path,
            'clipboard_max_count': clipboard_max_count,
            'volume_limit': volume_limit,
            'volume_target': volume_target,
            'translation_mode': translation_mode,
            'ocr_mode': ocr_mode,
            'ocr_model_path': ocr_model_path,
            'ocr_mmproj_path': ocr_mmproj_path,
            'sentence_punctuations': normalized,
            'mouse_landmarks': normalized_landmarks
        }
        logging.info(f"保存配置: ocr_mode={ocr_mode}, ocr_model_path={ocr_model_path!r}, ocr_mmproj_path={ocr_mmproj_path!r}")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"保存配置失败: {e}")


def get_mouse_landmark(app_id: str, slot) -> list:
    """读取指定应用某槽位的路标坐标，未标记返回 None"""
    slots = globals()['mouse_landmarks'].get(app_id) or {}
    pos = slots.get(str(slot))
    return list(pos) if pos else None


def set_mouse_landmark(app_id: str, slot, x: float, y: float) -> bool:
    """记录指定应用某槽位的路标坐标并立即持久化到配置文件，返回是否写入成功"""
    try:
        config = {}
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        # 以文件中的路标为基线做槽位级合并，保留其他实例写入的数据，再用本进程内存覆盖
        merged = _normalize_mouse_landmarks(config.get('mouse_landmarks'))
        for cur_app, cur_slots in globals()['mouse_landmarks'].items():
            merged.setdefault(cur_app, {}).update(cur_slots)
        merged.setdefault(app_id, {})[str(slot)] = [float(x), float(y)]
        globals()['mouse_landmarks'] = merged
        # 仅更新路标字段，保留配置文件中的其余配置项
        config['mouse_landmarks'] = merged
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.warning(f"保存鼠标路标失败: {e}")
        return False


def _get_clipboard_data_path():
    """获取剪贴板数据文件路径"""
    app_data_dir = os.path.expanduser("~/Library/Application Support/MagicToolbox")
    os.makedirs(app_data_dir, exist_ok=True)
    return os.path.join(app_data_dir, ".clipboard_data")


def load_clipboard_data(max_count: int = 1000):
    import pickle
    data_path = _get_clipboard_data_path()
    try:
        if os.path.exists(data_path):
            with open(data_path, "rb") as f:
                encrypted_data = f.read()
            decrypted_data = _fernet.decrypt(encrypted_data)
            data = pickle.loads(decrypted_data)
            if len(data) > max_count:
                data = data[:max_count]
            logging.info(f"加载剪贴板数据成功，共 {len(data)} 条")
            return data
    except Exception as e:
        logging.warning(f"加载剪贴板数据失败: {e}")
    return []


def save_clipboard_data(data):
    import pickle
    data_path = _get_clipboard_data_path()
    try:
        pickled_data = pickle.dumps(data)
        encrypted_data = _fernet.encrypt(pickled_data)
        with open(data_path, "wb") as f:
            f.write(encrypted_data)
        logging.debug(f"保存剪贴板数据成功（{len(data)} 条）")
    except Exception as e:
        logging.error(f"保存剪贴板数据失败: {e}")


def filter_clipboard_records(records: list, keyword: str) -> list:
    """筛选剪贴板记录，返回包含关键词的记录"""
    if not keyword:
        return records
    keyword_lower = keyword.lower()
    return [r for r in records if keyword_lower in r.lower()]


def get_locale_dir():
    """获取 locales 目录路径"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "locales")


def is_internal_device() -> bool:
    """检测是否为内部电脑（通过检测 Self Service.app 是否存在）

    Returns:
        True: 内部电脑（存在 Self Service.app）
        False: 外部电脑（不存在 Self Service.app）
    """
    try:
        return os.path.exists("/Applications/Self Service.app")
    except Exception:
        return True


def is_internal_locked() -> bool:
    """内部机生产限制判定：内部电脑且未通过 debug_config.json 开启调试标志

    所有"内部机只开放 Apple"的入口（配置钳制、工具栏禁用、引擎切换热键等）
    统一使用本判定，避免各处散写遗漏
    """
    return is_internal_device() and not DEBUG_BUILD


def get_system_version() -> tuple:
    """获取系统版本，返回 (major, minor)
    
    Returns:
        (major, minor): 系统版本号
        (0, 0): 获取失败
    """
    try:
        result = subprocess.run(['sw_vers', '-productVersion'], capture_output=True, text=True)
        version_str = result.stdout.strip()
        if '.' in version_str:
            parts = version_str.split('.')
            return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        return (int(version_str), 0)
    except Exception:
        return (0, 0)


def supports_apple_translation() -> bool:
    """检测是否支持 Apple Translation Framework

    Returns:
        True: 支持 (macOS 26.0+，无头 TranslationSession API)
        False: 不支持
    """
    version = get_system_version()
    if version[0] == 0:
        return False
    return version[0] >= 26


class TranslationMode:
    """翻译模式常量"""
    LLM = "llm"
    APPLE = "apple"


APPLE_TRANSLATION_LANG_MAP = {
    "English": "en",
    "Chinese": "zh-Hans",
    "Traditional Chinese": "zh-Hant",
    "French": "fr",
    "German": "de",
    "Spanish": "es",
    "Japanese": "ja",
    "Korean": "ko",
    "Portuguese": "pt",
    "Italian": "it",
    "Russian": "ru",
    "Arabic": "ar",
    "Turkish": "tr",
    "Thai": "th",
    "Vietnamese": "vi",
    "Malay": "ms",
    "Indonesian": "id",
    "Filipino": "tl",
    "Hindi": "hi",
    "Polish": "pl",
    "Czech": "cs",
    "Dutch": "nl",
    "Hebrew": "he",
    "Ukrainian": "uk"
}


def get_current_locale():
    """获取当前语言环境"""
    return _locale


def load_help_content(filename: str) -> str:
    """加载帮助文档内容"""
    locale_dir = get_locale_dir()
    locale = get_current_locale()
    file_path = os.path.join(locale_dir, locale, filename)
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
    except Exception as e:
        logging.warning(f"加载帮助文档失败: {e}")
    return ""


_('menubar_help')
_('menu_help_program')
_('menu_help_shortcuts')
_('menu_help_changelog')
_('menu_help_donate')
_('menu_help_download_model')
_('menu_help_feedback')
_('help_load_failed')
_('donate_title')
_('donate_content')
_('feedback_title')
_('feedback_content')
_('feedback_contact_btn')
_('download_model_title')
_('download_model_prompt')
_('version_expired_title')
_('version_expired_msg')
_('version_expiring_title')
_('version_expiring_msg')
_('menu_help_check_update')
_('update_available_title')
_('update_available_msg')
_('update_latest_title')
_('update_latest_msg')
_('update_check_failed_title')
_('update_check_failed_msg')
_('update_downloading_title')
_('update_downloading_msg')
_('update_download_success_title')
_('update_download_success_msg')
_('update_download_failed_title')
_('update_download_failed_msg')
_('permission_denied_title')
_('permission_denied_msg')
