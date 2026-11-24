# TVBox-Sources

FongMi 影视配置管理仓库 · 少而精 · 稳定优先 · V1.0

| 分类 | 正式收录 | 上限 |
|---|---:|---:|
| 电视剧 | 0 | 8 |
| 动漫 | 0 | 5 |
| 电影 | 0 | 8 |
| 短剧 | 0 | 5 |

当前为基础设施已部署、待授权来源的阶段。两份订阅为空，不能观看。

## 固定订阅
- [正式配置](https://raw.githubusercontent.com/OUISEDRG/TVBox-Sources/main/tvbox.json)
- [候选配置](https://raw.githubusercontent.com/OUISEDRG/TVBox-Sources/main/preview.json)
- sources/ 四类独立配置；主入口为平面去重列表，非客户端四标签页。

## 维护
每天北京时间 04:30 健康检测，10:00/22:00 上游元数据同步；GitHub 调度可能延迟。Actions 手动支持 check/sync/health/preview/build/full。只读检查通过后才运行维护，验证通过才提交完整生成结果，不强制推送。
健康检测仅针对明确审核的 HTTPS JSON API：分类、列表、详情、指定授权搜索词（如提供）；不测试视频。网络超时、403、429、重定向记未知；明确失败连续2天观察、3天隔离，连续2个不同日期成功且审核仍有效才恢复。备用源按近期检测率排序，样本不足使用人工评分。观察中的主力可由正常备用暂时接替。自动健康检查拟隔离至少半数原正式站点时暂停批量变更、保留原注册表并标记 bulk_loss_hold 待人工处理；已明确的安全/授权撤销仍应人工立即隔离。代码、密钥、原始上游内容不会写入报告。
上游同步仅统计公开配置结构，不导入站点或自动替换 API。第三方 JAR/JS/Python 与 SHA-256 依赖校验、同服务深层去重、播放授权样本检测仍未支持；不得宣称全部实现。

## 首批审核
2026-11-25 已读取五组候选配置，均未确认内容授权及依赖安全。qist 与高天流云 README 限制使用/转载并不保证合法性；肥猫、王二小、饭太硬为镜像，不能证明原内容授权。当前 0 个通过审核，禁止导入整包。最新统计见 reports/health.json，来源见 config/upstreams.json。
红果、七猫、河马仅发现第三方爬虫条目，未证明有正式开放接口或授权。

## 真机验收与正式上线
待合法候选进入 preview 后：用户用 FongMi 检查首页、搜索、详情、实际播放、拖动和切集，提供站点名称/版本/结果/时间及主力选择。维护者确认授权、安全、兼容记录和人工评分（80+）后，将该站点 approved/playback_verified 设为 true、状态 active，运行 build/check 并提交。未经反馈不得提前发布。背景为暖米白图片；全局主题、海报比例须客户端验证。

详见 AGENTS.md。运行：`python3 scripts/test.py`，`python3 scripts/sync.py --check`。
