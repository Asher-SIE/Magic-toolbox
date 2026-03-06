# MagicToolbox

MagicToolbox is an accessibility-focused macOS application designed for VoiceOver users, providing real-time translation, clipboard management, and text processing features.

## Features

### Translation
- **Real-time Translation**: Instantly translate content read by VoiceOver
- **Multi-language Support**: Supports 38+ languages including English, Chinese, French, Japanese, Korean, Spanish, and more
- **Offline Translation**: Uses Tencent Hunyuan large model (requires downloaded model file), works without internet connection

### Clipboard Management
- **History**: Automatically saves clipboard content with history browsing
- **Multi-select**: Check multiple items for batch copy/delete operations
- **Built-in Editor**: Text editor with undo/redo support (⌘Z / ⌘⇧Z)
- **Quick Processing**: Remove whitespace, merge spaces, numbers to Chinese, sentence splitting

### Text Processing
- Remove whitespace characters (⌥+1)
- Merge multiple spaces to single space (⌥+2)
- Convert Arabic numerals to Chinese (⌥+3)
- Convert punctuation to newlines/sentences (⌥+4)

### VoiceOver Enhancement
- **VoiceOver Integration**: Designed specifically for VoiceOver, seamless screen reader integration
- **Character Explanation**: View detailed explanation of individual characters
- **Row/Column Statistics**: Real-time display of current text position

## Requirements

- macOS 12.0+
- Python 3.10+
- Homebrew (for dependency installation)

## Installation

### 1. Clone the Project

```bash
git clone <repository-url>
cd Magic-toolbox
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Download Translation Model

Translation requires Tencent Hunyuan large model (GGUF format):

1. Visit Hugging Face to download model file (e.g., `hunyuan-*.gguf`)
2. Place the model file in any directory
3. When running the app for the first time, select the model file through Settings panel

### 5. Run the Application

```bash
python main_UI.py
```

## Usage

### Interface Navigation

The app uses left navigation + right content panel layout:

- **Translation Panel**: Enter text for translation
- **Clipboard Panel**: Browse and manage clipboard history
- **Settings Panel**: Configure translation model path

### Keyboard Shortcuts

| Shortcut | Function |
|----------|----------|
| ⌥+1 | Remove whitespace |
| ⌥+2 | Merge multiple spaces |
| ⌥+3 | Numbers to Chinese |
| ⌥+4 | Punctuation to newlines |
| ⌥+C | Current character explanation |
| ⌥+D | English to Chinese (VO content) |
| ⌥+⇧+D | Chinese to English (VO content) |
| ⌥+T | Open clipboard editor |
| ⌥+A | Append VO content to list |
| ⌥+⇧+7 | Previous clipboard item |
| ⌥+⇧+8 | Previous line in clipboard |
| ⌥+⇧+9 | Next clipboard item |
| ⌥+⇧+J | Set clipboard content to system |
| ⌥+⇧+K | Next line in clipboard |
| ⌥+⇧+U | Previous character |
| ⌥+⇧+I | Character explanation |
| ⌥+⇧+O | Next character |
| ⌥+⇧+M | Clipboard summary (row/column info) |
| ⌘+Z | Undo (editor) |
| ⌘+⇧+Z | Redo (editor) |

### Text Editor

When editing clipboard content, supported shortcuts:

- **⌘Z**: Undo
- **⌘⇧Z**: Redo
- **⌥+1-4**: Quick text processing
- **Esc**: Cancel editing

## Build & Package

### Using Build Script

```bash
chmod +x build.command
./build.command
```

After packaging, the app will be generated at `dist/MagicToolbox.app`

### Notes

- Ensure `resources` directory exists with necessary resource files
- First-time packaging requires PyInstaller: `pip install pyinstaller`

## Project Structure

```
Magic-toolbox/
├── main_UI.py          # Main UI code
├── processer.py        # Core processor (translation, clipboard, VO)
├── setting.py          # Configuration & i18n
├── resources/          # Resource files
│   └── dict.txt        # Local dictionary
├── locales/            # i18n files
│   ├── zh_CN/          # Chinese translations
│   └── en/             # English translations
├── build.command       # Build script
├── MagicToolbox.spec   # PyInstaller config
└── requirements.txt   # Python dependencies
```

## Tech Stack

- **GUI**: wxPython 4.2
- **Translation Model**: llama.cpp + Tencent Hunyuan
- **System Integration**: appscript, PyObjC
- **Packaging**: PyInstaller

## Version

- Current Version: V1.0.3
- Build: 251230

## Support & Feedback

MagicToolbox is free and open source software. If you find it helpful, your support is appreciated!

- Email: asher.sie@gmail.com

Feel free to reach out for any questions or suggestions. Thank you for your support!

## License

MIT License
