# Eta GitHub-only 发布流程

## 当前边界

- `Eta CI` 仅在 Pull Request 和 `main` 上执行测试、lint、未签名 Debug/Release 构建。
- `Eta Vision Probe` 仅允许 `workflow_dispatch`，使用 `vision-probe` Environment；模型 ID 必须精确来自 `/v1/models`，每个模型/协议连续两次 PASS 才通过。
- `Eta Release Gate` 仅允许 `workflow_dispatch`。预检会检查 main CI 成功、版本名/版本码、唯一标签、版本码严格递增和版本 ledger。
- 生产签名 Secrets 只存在于 `release` Environment 的审批后 job；PR/main 不读取它们。
- 当前 Release Gate 停在发布前：不会创建 tag、正式签名生产 APK 或创建/发布 GitHub Release。

## 版本 ledger 与后续 Gate

版本基线见 `.github/version-ledger.json`。后续获批发布时，维护者应在 PR 中更新 `versionName`、严格递增 `versionCode` 和 ledger，再由 GitHub Actions 预检唯一的 `v<versionName>` 标签及最新 main CI。证书 SHA-256 指纹通过 `ETA_RELEASE_CERT_SHA256` 校验，证书内容和密码不得进入 Git。

Release Gate 单独批准后，才允许在 GitHub 的 `release` Environment 运行生产签名步骤。正式创建 tag、创建 Draft Release、上传 APK、发布 Release 均属于后续独立授权；本仓库不提供本机打包、打 tag、上传或发布指引。
