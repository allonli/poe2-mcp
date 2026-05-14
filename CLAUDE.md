## 项目约定（本仓库）

### PoB（Path of Building）导入

- `import_pob` 需要兼容两类输入：
  - 标准 Base64
  - URL-safe Base64（poe.ninja / pobb.in 常见，使用 `-` / `_`，并可能缺少 `=` padding）
