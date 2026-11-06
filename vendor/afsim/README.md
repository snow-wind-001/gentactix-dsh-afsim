# AFSIM 组件工作区

本目录将 AFSIM 集成所需的参考组件与本机运行依赖放在工程内，便于离线开发、复制与后续打包。

- `afsim-skill/`：`qingzhoupro/afsim-skill` 的固定版本；用于语法检索、模板与错误索引，不作为运行时裁判。
- `afsim-mcp/`：`Yookio-Z/AFSIM_MCP` 的固定版本；用于类型查询、场景执行和结果解析。保留上游代码与 MIT 许可证。
- `dependencies.lock.json`：来源、版本和许可记录。
- `local/afsim/runtime/`：用户本机 AFSIM Windows 运行文件。
- `local/afsim/compat/`：Ubuntu 下的局部 Wine 兼容层与解包工具，没有安装到系统目录。
- `local/afsim/wineprefix/`：本次验证专用 Wine 用户目录。
- `local/afsim/afsim-2.9.0-win64.7z`：本机分卷包还原的原始归档，保留后续重新解包能力。

`local/` 被 Git 忽略。AFSIM 本体、其源码与附带内容的使用及分发以原提供方条件为准，MIT 组件的许可不能覆盖 AFSIM 本体。不能将这里的所有文件自动加入公开 GitHub Release。

Windows 原生运行无需 Wine；Ubuntu 验证使用项目内 Wine。Python 宿主、操作系统基本库属于运行环境要求，正式发行时应由对应平台的打包流程冻结或提供，不能把 Linux 虚拟环境当成 Windows 解释器。

架构与能力验收见 [实施规划](../../docs/AFSIM与DSH态势分离实施规划.md)。
