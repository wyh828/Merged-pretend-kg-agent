# 数据怎么分享和使用

A、B、C 是同一份研究数据的三种用法，可以一起下载。

| 下载包 | 适合谁 | 怎么开始 |
|---|---|---|
| A 数据文件 | 想用 Python 分析或继续实验的人 | 解压后看 README，数据在 dataset 里 |
| B 图谱备份 | 想用 Neo4j 查询关系的人 | 用包内注明的 Neo4j 版本，恢复到一个新的空目录 |
| C 看板和统计 | 想先了解成果的人 | 解压后双击 dashboard.html |

这些数据目前用于准备和探索，正式全量预测还没完成。两种来源会重叠，数量不能直接相加。Crossref 许可不明确的摘要从分享副本去掉，本机原始文件保留。

## 下载后先检查文件

在项目根目录运行下面的命令，把路径换成自己下载的 ZIP：

```powershell
python Attempt/scripts/verify_share_00.py '下载目录/data_share_00.zip'
```

A 包逐行保存 JSONL 数据。把本地 `.env` 的 `DATA_DIR` 指向解压后的 `dataset/technology_trends_01`，不需要沿用别人的盘符。密码和 API Key 自己配置，不放进共享包。

## B 包怎么恢复

包内 database_00.json 写明数据库名和镜像版本。先准备一个全新的空数据目录，关闭要恢复的数据库，再使用对应版本的 `neo4j-admin database load neo4j --from-path=/backups`。把 B 包目录挂载为 `/backups`，新数据目录挂载为 `/data`。恢复后设置自己的账号密码，再启动 Neo4j。不要把备份导入正在使用的数据库目录。

## 本机怎么生成分享包

先离线导出研究数据库，并在另一个空目录恢复一次。恢复结果记录必须对应 dump 的 SHA-256；检查成功后运行：

```powershell
python Attempt/scripts/export_share_00.py --neo4j-dump '备份目录/neo4j.dump' --graph-validation '备份目录/restore_validation_00.json'
```

输出放在 Data/Exports 的新编号目录。工具不会替你停数据库或上传；原始数据、已有备份和旧实验结果都保留。三个 ZIP 都包含逐文件 SHA-256 清单，发布时绑定生成它们的代码提交。
