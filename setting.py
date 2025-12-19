import plistlib
import os


#  字符集合
chars_dict = {
    'zh': {
        ' ': '空格',
        '\n': '换行',
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
        'A': '大写A',
        'B': '大写B',
        'C': '大写C',
        'D': '大写D',
        'E': '大写E',
        'F': '大写F',
        'G': '大写G',
        'H': '大写H',
        'I': '大写I',
        'J': '大写J',
        'K': '大写K',
        'L': '大写L',
        'M': '大写M',
        'N': '大写N',
        'O': '大写O',
        'P': '大写P',
        'Q': '大写Q',
        'R': '大写R',
        'S': '大写S',
        'T': '大写T',
        'U': '大写U',
        'V': '大写V',
        'W': '大写W',
        'X': '大写X',
        'Y': '大写Y',
        'Z': '大写Z',
        '٠': '数字0',
        '٩': '数字9',
        '٨': '数字8',
        '٧': '数字7',
        '٦': '数字6',
        '٥': '数字5',
        '٤': '数字4',
        '٣': '数字3',
        '٢': '数字2',
        '١': '数字1',
        '，': '全角逗号',
        '。': '句号',
        '？': '全角问号',
        '！': '全角感叹号',
        '：': '全角冒号',
        '；': '全角分号',
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
        'A': 'cap A',
        'B': 'cap B',
        'C': 'cap C',
        'D': 'cap D',
        'E': 'cap E',
        'F': 'cap F',
        'G': 'cap G',
        'H': 'cap H',
        'I': 'cap I',
        'J': 'cap J',
        'K': 'cap K',
        'L': 'cap L',
        'M': 'cap M',
        'N': 'cap N',
        'O': 'cap O',
        'P': 'cap P',
        'Q': 'cap Q',
        'R': 'cap R',
        'S': 'cap S',
        'T': 'cap T',
        'U': 'cap U',
        'V': 'cap V',
        'W': 'cap W',
        'X': 'cap X',
        'Y': 'cap Y',
        'Z': 'cap Z',
        '٠': 'digit 0',
        '٩': 'digit 9',
        '٨': 'digit 8',
        '٧': 'digit 7',
        '٦': 'digit 6',
        '٥': 'digit 5',
        '٤': 'digit 4',
        '٣': 'digit 3',
        '٢': 'digit 2',
        '١': 'digit 1',
        '，': 'full-width comma',
        '。': 'full-width period',
        '？': 'full-width question mark',
        '！': 'full-width exclamation mark',
        '：': 'full-width colon',
        '；': 'full-width semicolon',
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


# 语言字典
lang_dict = {
    'zh': {
        'app_name': 'Magic Toolbox',
        'editor_title': '编辑剪贴板内容',
        'tbr_mode': '模式',
        'trans_radio': '翻译',
        'clipboard_radio': '剪贴板',
        'copy_btn': '拷贝',
        'copy_btn_tips': '复制到剪贴板',
        'delete_btn': '删除',
        'delete_btn_tips': '删除选中项',
        'edit_btn': '编辑',
        'edit_btn_tips': '编辑选中项',
        'confirm_btn': '确定',
        'cancel_btn': '取消',
        'vo_warning': '获取VoiceOver朗读内容失败',
        'model_warning': '翻译模型加载失败,仅保留本地词典功能',
        'menu_about': '关于 Magic Toolbox',
        'menubar_opt': '操作',
        'menu_opt_rebootVO': '重启旁白',
        'menu_opt_reboot_proc': '重启处理器',
        'menu_opt_clean_list': '清空剪贴板列表',
        'about_dialog': ''' ''',
        'now': '当前',
        'row': '行',
        'column': '列',
        'total_chars': '个字',
        'edd_more_btn': '更多',
        'edd_remove_whitespace_btn': '删除所有空白符',
        'edd_merge_spaces_btn': '合并连续空格',
        'edd_num_to_chinese_btn': '数字转中文',
        'edd_punc_to_newline_btn': '分句',
        'msg_motice': '提示',
        'msg_is_close': '确定要退出吗？',
    },
    'en': {
'app_name': 'Magic Toolbox',
        'editor_title': 'Edit clipboard contents',
        'tbr_mode': 'Mode',
        'trans_radio': 'Translation',
        'clipboard_radio': 'Clipboard',
        'copy_btn': 'Copy',
        'copy_btn_tips': 'Copy to clipboard',
        'delete_btn': 'Delete',
        'delete_btn_tips': 'Delete current item',
        'edit_btn': 'Edit',
        'edit_btn_tips': 'Edit current item',
        'confirm_btn': 'OK',
        'cancel_btn': 'Cancel',
        'vo_warning': 'Getting VoiceOver Reading Failed',
        'model_warning': 'Translation model loading failed, retaining only local dictionary functions',
        'menu_about': 'About Magic Toolbox',
        'menubar_opt': 'Operation',
        'menu_opt_rebootVO': 'Reboot VoiceOver',
        'menu_opt_reboot_proc': 'Reboot Processer',
        'menu_opt_clean_list': 'Empty Clipboard List',
        'now': 'Is',
        'row': 'Row',
        'column': 'Column',
        'total_chars': 'Characters',
        'edd_more_btn': 'More',
        'edd_remove_whitespace_btn': 'Remove All Whitespace',
        'edd_merge_spaces_btn': 'Merge Consecutive Spaces',
        'edd_num_to_chinese_btn': 'Convert Numbers to Chinese',
        'edd_punc_to_newline_btn': 'Split into Sentences',
        'msg_motice': 'Notice',
        'msg_is_close': 'Are you sure you want to quit?'
    }
}


def get_system_language():
    """通过读取系统plist文件获取macOS语言设置"""
    try:
        # macOS语言设置存储路径
        plist_path = os.path.expanduser("~/Library/Preferences/.GlobalPreferences.plist")
        
        # 读取plist文件
        with open(plist_path, 'rb') as f:
            plist_data = plistlib.load(f)
        
        # 获取首选语言列表
        apple_languages = plist_data.get('AppleLanguages', [])
        print(f"首选语言列表: {apple_languages}")
        
        if not apple_languages:
            print("未找到语言设置")
            return 'en'
            
        # 取第一个语言作为首选语言
        primary_lang = apple_languages[0]
        print(f"首选语言: {primary_lang}")
        
        if primary_lang.startswith('zh'):
            return 'zh'
        else:
            return 'en'
            
    except FileNotFoundError:
        print("未找到语言设置文件")
        return 'en'
    except Exception as e:
        print(f"获取语言失败: {str(e)}")
        return 'en'


# 全局语言变量
current_lang = get_system_language()

#快捷键定义
hotKeys = [
    {
        "name": "altc",
        "modifiers": ["ALT"],
        "key": "c",
        "handler": "on_hotkey_altc",
        "description": "Alt+c查字典和英译中"
    },
    {
        "name": "altshiftc",
        "modifiers": ["ALT", "SHIFT"],
        "key": "c",
        "handler": "on_hotkey_altshiftc",
        "description": "alt+shift+c中译英"
    },
    {
        "name": "altt",
        "modifiers": ["ALT"],
        "key": "t",
        "handler": "on_hotkey_altt",
        "description": "alt+T剪贴板编辑器"
    },
    {
        "name": "altd",
        "modifiers": ["ALT"],
        "key": "d",
        "handler": "on_hotkey_altd",
        "description": "alt+d VO添加到列表第一行"
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
        "description": "alt+shift+7: 剪贴板列表上一条"
    },
    {
        "name": "altshift8",
        "modifiers": ["ALT", "SHIFT"],
        "key": "8",
        "handler": "on_hotkey_altshift8",
        "description": "alt+shift+8: 当前剪贴板上一行"
    },
    {
        "name": "altshift9",
        "modifiers": ["ALT", "SHIFT"],
        "key": "9",
        "handler": "on_hotkey_altshift9",
        "description": "alt+shift+9: 剪贴板列表下一条"
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
        "description": "a lt+shift+k: 当前剪贴板下一行"
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
    }
]

