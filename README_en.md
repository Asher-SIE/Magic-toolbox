# MagicToolbox
MagicToolbox is an assistive tool designed exclusively for macOS VoiceOver visually impaired users, integrating core features including real-time translation, clipboard management, and one-click text processing.

## Features
### Translation Features
- **Real-time Translation**: Supports instant translation of content read aloud by VoiceOver
- **Multi-language Support**: Supports over 38 languages, including English, Chinese, French, Japanese, Korean, Spanish, etc.
- **Offline Translation**: Powered by the Tencent Hunyuan Large Language Model (model file must be downloaded separately), works without an internet connection

### Clipboard Management
- **History Records**: Automatically saves clipboard content and supports browsing history
- **Multi-selection Operations**: Supports checking multiple records for batch copy and delete operations
- **Editing Function**: Built-in text editor with undo and redo functionality
- **Quick Processing**: Provides handy features including removing blank spaces, merging spaces, converting numbers to Chinese characters, and text splitting

### Voice Enhancement
- **VoiceOver Integration**: Optimized for VoiceOver, works seamlessly with the screen reader
- **Character Explanation**: Supports viewing detailed explanations of individual characters
- **Content Appending**: Supports appending and copying text read aloud by VoiceOver

## Usage
### Interface Navigation
The app uses a layout with a left navigation bar and a right content panel:
- **Translation Panel**: Enter text to perform translation
- **Clipboard Panel**: Browse and manage clipboard history
- **Settings Panel**: Configure the translation model path and the maximum number of saved clipboard records

### Keyboard Shortcuts
| Shortcut | Function |
|--------|------|
### 1. Text Translation / Explanation Shortcuts
| Option+C | Explain current character |
| Option+D | Translate the last text read aloud by VoiceOver |
| Option+Shift+D | Reverse translation |
| Option+Enter | Translate content in the edit box of the translation interface |
| Option+Shift+Enter | Reverse translate content in the edit box of the translation interface |

### 2. Clipboard Editor Shortcuts
| Option+T | Open clipboard editor |
| Option+1 | Remove blank characters |
| Option+2 | Merge multiple spaces |
| Option+3 | Convert numbers to Chinese characters |
| Option+4 | Split text into lines |
| Option+F | Find next |
| Option+Shift+F | Find previous |
| Option+H | Open replace dialog |
| Command+Z | Undo |
| Command+Shift+Z | Redo |
| Escape | Exit editor |
| Option+X | Save edits and exit editor |

### 3. Text Browsing Shortcuts
| Option+A | Append and copy content read aloud by VoiceOver |
| Option+Shift+7 | Previous item in clipboard list |
| Option+Shift+8 | Previous line of current clipboard content |
| Option+Shift+9 | Next item in clipboard list |
| Option+Shift+U | Previous character of current clipboard content |
| Option+Shift+I | Explain current character in clipboard browsing mode |
| Option+Shift+O | Next character of current clipboard content |
| Option+Shift+J | Sync clipboard content to system clipboard |
| Option+Shift+K | Next line of current clipboard content |
| Option+Shift+M | View clipboard summary (row and column information) |

## System Requirements
- macOS 12.0 or later
- Python 3.10 or later
- Homebrew (for installing project dependencies)

## Installation Steps
### 1. Clone the Repository
```bash
git clone <repository-url>
cd Magic-toolbox
```

### 2. Create a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Download the Translation Model
The translation function requires the Tencent Hunyuan Large Language Model (GGUF format):
1. Visit the Hugging Face platform to download the model file
2. Save the model file to any local directory
3. On the first run, select the model file path via the built-in Settings panel

### 5. Run the Application
```bash
python main_UI.py
```

## Build & Package
### Using the Build Script
```bash
chmod +x build.command
./build.command
```
After packaging, the application file will be generated in the `dist/MagicToolbox.app` directory.

### Notes
- Ensure the `resources` folder exists in the project root directory and contains all necessary resource files
- Before the first packaging, install the packaging tool: `pip install pyinstaller`

## Project Structure
```
Magic-toolbox/
├── main_UI.py          # Main interface code
├── processer.py        # Core processor (translation, clipboard, VoiceOver functions)
├── setting.py          # Configuration and internationalization module
├── resources/          # Resource files directory
│   └── dict.txt        # Local dictionary file
├── locales/            # Internationalization language files
│   ├── zh_CN/          # Chinese language pack
│   └── en/             # English language pack
├── build.command       # Project packaging script
├── MagicToolbox.spec   # PyInstaller packaging configuration file
└── requirements.txt    # Python dependency list
```

## Tech Stack
- **GUI Framework**: wxPython 4.2
- **Translation Model**: llama.cpp + Tencent Hunyuan Large Language Model
- **System Integration**: appscript, PyObjC
- **Packaging Tool**: PyInstaller

## License
MIT License