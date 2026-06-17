# OpenSearch 2.19.3 搜索方案验证工程

本工程用于验证 OpenSearch 2.19.3 下，结构化设备表项与非结构化设备配置的 IP、MAC、普通文本精确/模糊检索、高亮和配置行号方案。

## 当前已验证环境

- OpenSearch: `2.19.3`
- OpenSearch build hash: `a90f864b8524bc75570a8461ccb569d2a4bfed42`
- Lucene: `9.12.2`
- OpenSearch image digest: `sha256:e96cc6ae1500a073d973c0906f30f7cf4d9c461f32f855f9242a2da933660cdd`
- OpenSearch Dashboards image digest: `sha256:19e0dd30c7086e933cf475726d92ccc98be26ced9f0c4e4a2a3ae6d9539280a3`

当前机器上已启动：

- OpenSearch: http://localhost:9200
- OpenSearch Dashboards: http://localhost:5601

## 快速复现

如果 9200/5601 没有被已有容器占用，可以使用 compose：

```bash
docker compose -f docker/docker-compose.yml up -d
```

如果使用当前已运行的 OpenSearch，也可以直接写入 mock 数据并验证：

```bash
python3 scripts/setup_demo.py
python3 scripts/verify_search.py
```

生成 Excel 评估表：

```bash
bash scripts/build_evaluation_workbook.sh
```

`build_evaluation_workbook.sh` 会先运行 `scripts/generate_search_matrix.py`，生成完整实测矩阵
`outputs/search-matrix-results.json`，再用该 JSON 生成 Excel。

## 主要产物

- `docker/docker-compose.yml`: digest pinning 的 OpenSearch 与 Dashboards 2.19.3 环境。
- `opensearch/indices/structured-devices-v1.json`: 结构化索引定义。
- `opensearch/indices/device-configs-v1.json`: 非结构化配置索引定义，只保留 `config` 主字段并增加子字段。
- `opensearch/search-requests/*.json`: 可复用搜索报文。
- `scripts/setup_demo.py`: 创建索引并写入 mock 数据。
- `scripts/verify_search.py`: 自动化验证精确搜索、跨格式 MAC、模糊搜索、高亮、配置行号。
- `data/mock-documents.json`: mock 数据快照。
- `outputs/verification-report.json`: 验证结果。
- `outputs/search-matrix-results.json`: 实际字段、实际输入、实际搜索方式、实际 OpenSearch 返回结果组成的完整交叉矩阵。
- `outputs/opensearch-search-evaluation-2.19.3.xlsx`: 多维度 Excel 评估表，包含紧凑交叉对比和干扰样例分析 sheet。
- `docs/search-solution.md`: 本业务搜索方案说明。
- `docs/opensearch-index-search-manual.md`: OpenSearch 索引配置与搜索能力说明书。
- `docs/business-search-api-design.md`: 封装后的业务搜索 REST 接口设计文档。
