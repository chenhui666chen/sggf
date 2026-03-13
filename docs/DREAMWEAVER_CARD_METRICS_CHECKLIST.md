# 织梦映心卡片改造指标观测清单（7天）

## 目标

- 验证卡片改造是否提升“进入生成流程”效率。
- 监控删除风险是否下降。
- 监控未命名项目是否被有效重命名。

## 已接入事件

- `project_card_click`：点击整卡进入生成流程。
- `project_primary_action_click`：点击“继续创作”按钮进入生成流程。
- `project_more_menu_open`：打开“更多操作”菜单。
- `project_library_open`：进入素材库。
- `project_delete_click`：打开删除确认弹窗。
- `project_delete_confirm`：确认删除（含成功/失败）。
- `project_rename_start`：开始重命名。
- `project_rename_save`：保存重命名（含成功/失败）。
- `project_rename_from_untitled`：未命名项目完成重命名。
- `project_search_used`：使用搜索。
- `project_filter_used`：使用题材筛选。

## 指标定义

1. 进入流程点击总量  
`project_card_click + project_primary_action_click`

2. 主按钮占比  
`project_primary_action_click / (project_card_click + project_primary_action_click)`

3. 删除确认成功率  
`project_delete_confirm(result=success) / project_delete_confirm(all)`

4. 未命名重命名率  
`project_rename_from_untitled / 待命名项目曝光数`  
说明：当前版本未单独埋“待命名曝光”，可先以日环比观察 `project_rename_from_untitled`。

5. 筛选与搜索使用率  
`project_search_used`、`project_filter_used` 的日次数变化。

## 每日检查项（D1-D7）

1. 检查 `ui.event.count` 是否持续增长（确认埋点稳定）。
2. 检查 `project_delete_confirm` 的 `result=failure` 是否异常升高。
3. 检查 `project_primary_action_click` 占比是否逐步上升。
4. 检查 `project_search_used` 与 `project_filter_used` 是否出现断崖（疑似前端回归）。
5. 对比改造前后同周期“进入流程总量”。

## 查询方式

- 聚合指标接口：`GET /api/v1/monitoring/metrics`
- 仪表板接口：`GET /api/v1/monitoring/dashboard`
- 前端埋点接收：`POST /api/v1/monitoring/frontend-event`

建议在灰度期（5% -> 20% -> 50% -> 100%）每个阶段至少观察 24 小时后再扩大流量。
