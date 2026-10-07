# Docker 启动问题记录

2026-10-07，Docker Desktop 启动时报 dockerInference 文件无法访问。随后也出现 Secrets Engine 的 engine.sock 同类错误；两处通信目录备份重建后，首次错误再次出现，暂未恢复引擎。

已做的操作只涉及崩溃的 Desktop 进程和通信文件。没有执行出厂重置，没有删除镜像、卷、数据库或项目原始数据。

本机保留的备份位置：

- `%LOCALAPPDATA%/Docker/run_before_repair_20261007_00`
- `%LOCALAPPDATA%/docker-secrets-engine_before_repair_20261007_00`

Docker 官方问题仓库有 [相同 socket 启动问题的报告](https://github.com/docker/desktop-feedback/issues/448)。这个报告提供了线索，但本机重建后仍复现，不能直接认为已经修好。

后续先收集本机启动诊断，核对 Windows 与 Docker 版本及 AF_UNIX 通信支持；若需要重装或重置，先备份 Docker 的持久数据并单独确定操作范围。项目的 A/B/C 发布等待真实图谱导出和独立恢复验证。
