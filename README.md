# TVBox-Sources

面向 FongMi 的精简影视配置管理仓库。公开仓库，仅收录具有授权依据的资源。

当前状态：P0 初始化，0 个正式站点，0 个候选站点。尚未完成真机兼容和播放验证；空配置不可用于观看。

| 分类 | 上限 |
|---|---:|
| 电视剧 | 8 |
| 动漫 | 5 |
| 电影 | 8 |
| 短剧 | 5 |

## 订阅入口
- [正式配置](https://raw.githubusercontent.com/OUISEDRG/TVBox-Sources/main/tvbox.json)：尚无可观看站点。
- [候选配置](https://raw.githubusercontent.com/OUISEDRG/TVBox-Sources/main/preview.json)：待审核。
- sources/：分类配置

## 本地检查
```sh
python scripts/sync.py
python scripts/test.py
```
目前只实现本地配置生成、基本校验和测试。上游同步、网络健康检测、评分历史、依赖静态安全审核、实际播放及自动发布均未完成；定时更新保持禁用，防止空配置或未审核内容被误发布。

维护规则见 AGENTS.md。
