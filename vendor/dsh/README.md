# 本地 DSH SDK 构建

`requirements-dsh.txt`保留PyPI可安装的`0.2.1rc2`基线。本机升级候选为官方标签`dsh-v0.2.1-rc.5`的Python SDK及匹配运行时，两者必须一起安装；不能只更换SDK代码。

本地构建文件保存在忽略目录`local/0.2.1rc5/`，不包含用户配置、凭据和对局。`manifest.json`记录来源提交、平台、大小及SHA256。此Linux x86_64构建使用Python3.10以上；Windows需要另行构建验证。

安装现有本地产物（先安装项目其他依赖）：

```bash
python -m pip install --no-deps vendor/dsh/local/0.2.1rc5/*.whl
PYTHONPATH=. python tools/qa/dsh_sdk_upgrade.py --out .cache/qa/sdk-lifecycle
```

该检查使用回环地址的固定模型响应，但运行真实SDK与领域插件，验证分支、重启恢复和取消；不代表真实模型质量或战役验收。真实模型兼容另以`tools/qa/campaign_members_live.py --live --hierarchy`验证。

本机运行时构建做了三项局部调整：部署依赖沿用根锁文件、SEA使用GZip压缩、修复压缩包空文件传入`maxOutputLength=0`引发的Node错误（上限最少1字节）。补丁、锁版本生成器及`fix-empty-sea-entry.py`保存在同一忽略目录；修补采用文件替换，不改pnpm共享硬链接。运行时wheel约139MiB，超过上游发布脚本的PyPI单文件门限；这是本地产物，不是PyPI正式发行。上游两项“未打包插件须在initialize失败”的测试仍失败，不能声称上游测试全通过。

执行`pip install -r requirements-dsh.txt`会重新选择其中的确切版本；若需要本地rc5，随后成对重装本地wheel。不要在模型子进程运行时更换环境中的运行时文件。
