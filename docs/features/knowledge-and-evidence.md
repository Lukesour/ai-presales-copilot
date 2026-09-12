# 知识与证据

## 责任域

`knowledge.py`, `knowledge_store.py`, `ingestion.py`, `data/knowledge/` and their tests
及其测试负责来源登记、解析、检索、ACL 过滤和撤回行为。

## 边界

知识记录携带来源身份、版本、许可、定位信息、内容 hash、租户和 ACL 元数据。内容交给模型前，检索必须
先过滤授权、有效期和撤回状态。权威索引为空时不得静默回退到旧本地副本。

## 安全

远程导入要求已授权的 HTTPS 来源，并拒绝私网逃逸、未登记来源、超大输入和不安全重定向。撤回来源必须
按责任人流程从所有活跃索引中消失。

## 证据

- `docs/security-and-governance.md`
- `data/knowledge/README.md`
- `tests/test_v2_runtime.py`
- `scripts/ingest_sources.py`
