# =============================================================================

# AFSIM-SKILL | v1.0.2

# ==================================================

# Project: https://github.com/qingzhoupro/afsim-skill

# =============================================================================

# AFSIM-SKILL | v1.0.2

> English | [中文](README.md)

> **First time? 3 steps, 3 minutes.**

Works with Cursor / Trae / VSCode + Continue / Claude Desktop and any IDE that supports MCP protocol.

---

## Quick Start (3 Steps)

### Step 1: Open This Directory

Open the `AFSIM-SKILL/` directory as your project root in Cursor or Trae.

The IDE will automatically recognize:

- `.cursor/commands/` — command entries (`/afsim` `/afsim-auto` `/afsim-learn` `/afsim-debug`)
- `SKILL.md` — AI behavior specification

### Step 2: Start a Conversation

In the AI chat window, type:

```
/afsim
```

You will see the command list and quick start guide.

### Step 3: Choose a Subcommand


| Command            | When to Use                                                     |
| ------------------ | --------------------------------------------------------------- |
| `/afsim-auto`      | Quickly generate AFSIM scenario code (fully automatic)          |
| `/afsim-auto step` | Build module by module, great for learning or complex scenarios |
| `/afsim-learn`     | Parse your own MD/PDF docs into the skill                       |
| `/afsim-debug`     | Paste error messages to get fix suggestions                     |


---

## Features

- **AFSIM Code Generation**: Template + Demo based, accurate with minimal errors
- **Command-driven**: `/afsim-auto` full-auto / step-by-step / `/afsim-learn` doc parsing / `/afsim-debug` error handling
- **Progressive Disclosure**: Only core files loaded by default, details on demand, minimal context usage
- **Two-layer Lesson System**: Reflex-style error index + triggered deep lessons
- **Template Library**: From basic to advanced, copy and use
- **Extensible**: GUI plugin parameters, more Demo categories, lessons accumulate over time

---

## Gold Rule

> **Do not fabricate AFSIM syntax from scratch — base your output on verified templates and official Demos.**

---

## License

This project is open source under the [MIT License](LICENSE.md). Commercial use is welcome.

---

## About

AFSIM-SKILL is developed by **HaiKong BingQi (海空兵棋 / NAVGAME)**, specializing in AI-assisted development for Command series and AFSIM wargaming tools.

Related projects:

- CMO-HKBQSKILL — Command Lua code generation

**Follow our WeChat Official Account: 海空兵棋（NAVGAME)** for the latest wargaming tutorials, AFSIM tips, and AI-assisted development case studies.

Join our **知识星球** for in-depth discussions with wargaming enthusiasts across China.

---

## Changelog

### 2026-05-26 | v1.0.2

- Added `[E019]` weapon declaration inside platform instance error lesson
- Added `[E020]` output file relative path error lesson (relative to AFSIM startup directory)
- Added `[L014]` weapon declaration position lesson
- Added `[L015]` output file path lesson
- Enhanced two-layer lesson system

### 2026-05-25

- Initial release
- `/afsim-auto` full-auto / step-by-step code generation
- `/afsim-learn` doc parsing
- `/afsim-debug` error handling with two-layer lesson system
- Progressive disclosure, minimal context usage

---


*Licensed under MIT · [海空兵棋](http://www.nawgsoft.com)*