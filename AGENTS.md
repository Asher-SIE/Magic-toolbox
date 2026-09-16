# AGENTS.md

## 项目概述

MagicToolbox：专为 macOS VoiceOver 视障用户设计的辅助工具，Python + wxPython 实现，PyInstaller 打包。
集成实时翻译（LLM / Apple 翻译 + 本地词典）、剪贴板管理、文本快捷处理；注释与文案以中文为主，文案经 `locales/` 做 zh_CN/en 双语。
核心依赖（wxPython、appscript、pyobjc、llama_cpp）仅在 macOS 环境完整可用，无 wx/pytest 的环境按下方测试要求降级验证。

## 常用命令

- 测试：`python -m pytest tests/`；GUI 测试（如 `tests/test_ime_escape.py`）依赖 macOS + wx 真实显示环境，
  无该环境时最低要求：`python -m py_compile <改动的 .py>` 通过，且新增纯逻辑用独立断言验证。
- 文案编译：`bash msgfmt.sh`（`.po` 编译为 `.mo`；`.mo` 不入库，只提交 `.po`，改动需 zh_CN 与 en 同步）。

## 代码规范

Python：
- 命名：snake_case（函数/变量）、PascalCase（类）
- 类型标注：推荐标注
- 注释：中文，禁止输出装饰性字符，若有可移除

## 提交规范

1. 自动提交：改动完成并验证无 bug 后，直接提交当前分支，无需事先征询用户
2. 提交信息沿用仓库惯例：`type(scope): 中文描述`，type 取 fix/feat/docs/chore/refactor
3. 只提交本次任务相关文件，不带入工作区中他人/并行的无关改动

## Behavioral guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
