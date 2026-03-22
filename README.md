# AI Skills 索引

本仓库中所有可用的 Skill 列表。

> 所有 skill 均位于 `skills/` 目录下，可直接拷贝对应子目录进行安装部署。

| Skill | 版本 | 说明 | 目录 |
|-------|------|------|------|
| [dicom-doctor](skills/dicom-doctor/) | v0.7.0 | AI 辅助医学影像阅片：接收 DICOM 文件或 ZIP 压缩包，转换为 PNG，AI 逐张检视全部影像（检测结节、肿块、钙化等异常），生成 PDF 格式检查报告 | `skills/dicom-doctor/` |

## 快速安装

将 `skills/<skill名>/` 目录拷贝到目标环境即可使用：

```bash
# 安装单个 skill
cp -r skills/dicom-doctor /path/to/target/

# 批量安装所有 skill
cp -r skills/* /path/to/target/
```

## 相关目录

| 目录 | 说明 |
|------|------|
| `skills/` | 可直接安装的 skill（拖过去即用） |
| `openspec/` | 各 skill 的 OpenSpec 设计文档 |
| `doc/` | 补充文档 |
| `tests/` | 测试用例 |
