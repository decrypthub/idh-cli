# AGENTS.md — idh-cli

在 DecryptHub 聚合工作区中修改本仓前，先读 [共享 IDH 产品基线](../.cursor/rules/idh-product-baseline.mdc)，再对照 [手机端产品架构](../IOSDecryptHub/docs/PRODUCT_ARCHITECTURE.md)、[已验证进度](../IOSDecryptHub/docs/PROGRESS.md) 和本仓 `README.md`。独立检出本仓时，先读 `README.md` 并按当前代码与可用真机证据核对，不猜测缺失的设备端行为。

本仓是 IDH 的设备连接、电脑面板和 MCP 客户端；手机 `idhjd` 才是数据与配置的真源。改电脑端前核对原版实际操作与其后端，不以保留标签、展示摘要、接通一个测试地址或编译通过代替功能验收。保留现有连接和未提交工作；临时预览与真实设备状态分开报告。
