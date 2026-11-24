# TVBox-Sources

面向 FongMi 的精简影视配置管理仓库。公开仓库，仅收录具有授权依据的资源。

当前状态：P1 配置生成器初版；0 个正式站点，0 个候选站点。空配置不可用于观看。

| 分类 | 上限 |
|---|---:|
| 电视剧 | 8 |
| 动漫 | 5 |
| 电影 | 8 |
| 短剧 | 5 |

## 订阅入口
- [正式配置](https://raw.githubusercontent.com/OUISEDRG/TVBox-Sources/main/tvbox.json)：尚无可观看站点。
- [候选配置](https://raw.githubusercontent.com/OUISEDRG/TVBox-Sources/main/preview.json)：待审核。
- sources/：四类独立配置。正式入口为去重后的平面站点列表；FongMi 的分类切换和首页样式须真机确认。

## 当前实现
- 仅支持经过明确人工审核的直接 HTTPS JSON API（type=1），不加载第三方可执行代码。
- 候选与正式配置分开；正式站点须人工批准和真机验证。
- 分类限额、唯一 ID、重复 API、固定主力排序、隔离排除、最小字段输出。
- 注册表及策略是唯一来源，生成文件不得手工修改。
- 安全和授权审核字段必须有真实证据，不是自动证明。
- 目前不支持有查询参数的 API、外部 JAR/JS/Python、联网检测、自动发现、自动评分、自动故障转移与定时发布。以上功能均待开发审核。

## 本地检查
```sh
python scripts/sync.py
python scripts/sync.py --check
python scripts/test.py
```
GitHub Actions 当前只执行只读检查，不自动写入仓库。详见 AGENTS.md。
