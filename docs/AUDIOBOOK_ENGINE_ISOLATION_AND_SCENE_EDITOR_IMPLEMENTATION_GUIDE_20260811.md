# 有声书双引擎隔离与场景编辑器实施指导

> 文档状态：待实施
> 创建日期：2026-08-11
> 文档版本：R22（审查修订版 21）
> 最近修订：2026-08-15（R22：吸收第十八轮第三方审查 3 P1 + 1 补充建议——进度表状态值域与认领协议一致性（R22/P1-1：R21 进度表 CHECK 值域仅 pending/completed/failed，但认领协议反复依赖 running（“running 且租约有效跳过”“过期 running 接管”）——按当前 CHECK running 无法写入，这些分支是不可执行的死分支，且与“本版默认单实例”表述混杂误导实现；修复：采用审查推荐方案 A——本版仅支持全局单实例，status 保留 pending/completed/failed 三态，删除默认合同中全部 running/租约/接管死分支描述；多实例升级备注保留但明确届时需同步扩展 CHECK 值域）；事务 B fail-closed 防覆盖 completed（R22/P1-2：R21 未限定事务 B 的 upsert failed 条件——事务 A 已提交但客户端因断线/驱动异常误判失败时，直接 upsert failed 会把已提交的 completed 覆盖，导致已合并组被重复处理（重复 synthetic run/重复输出登记/错误二次改指）；修复：事务 B 必须为 fail-closed 条件更新 `ON CONFLICT DO UPDATE ... WHERE progress.status <> 'completed'`；提交结果不确定时先用新连接重读 progress：completed 且组级一致性校验通过视为成功，绝不写 failed；仅确认事务 A 未提交或 progress 仍非 completed 才执行事务 B；补真实 PostgreSQL 测试：事务 A commit → 模拟 commit 响应前断线 → 重试不得把 completed 改为 failed、不重复创建 synthetic run/output/文件登记）；会话锁专用连接与解锁合同（R22/P1-3：R21 的 `pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)` 是会话级锁，未定义专用连接与解锁合同——从连接池取连接获锁后异常归还但未 unlock，锁随池中连接存活，后续所有迁移实例持续获取失败直到连接被回收；修复：会话锁必须用专用、非池化 PostgreSQL 连接持有；获取失败立即关闭连接退出；正常完成/异常退出/取消信号均在 finally 执行 `pg_advisory_unlock` 后关闭专用连接；持锁连接不得归还连接池；进程崩溃依赖数据库断连自动释放并记录 run_id/host/pid；提供运维检查 SQL（pg_locks advisory + pg_stat_activity）定位长期持锁会话，人工确认后才 terminate 禁止自动 kill；补双场景测试：异常退出 finally 解锁 → 实例 B 获锁成功；进程死亡 → 断连释放 → 实例 B 重启）；attempts 递增语义（补充建议：attempts 仅在确认失败并写入事务 B 时递增——事务 A 已提交、客户端只是不确定结果的组不得递增，否则迁移报告把成功组误统计为有失败历史，干扰 Contract 准入与人工排障））
> 上一修订：2026-08-15（R21：吸收第十七轮第三方审查 2 P1 + 3 P2——迁移失败记录事务边界（R21/P1-1：R20 “进度与单组业务同事务写入”与“单组失败整体回滚”矛盾——failed 标记同事务写入会随回滚消失，迁移报告看不到失败组；修复：明确事务 A（组处理：认领/canonical 选择/改指/文件登记/校验/progress=completed，仅 completed 必须与业务数据同事务提交才可跳过）与事务 B（事务 A 回滚后的独立短事务：upsert failed + 脱敏 failure_detail + attempts+=1 + last_failed_at + last_error_code）；重试先读进度表 completed 并重跑组级一致性校验后跳过（不依赖调用方本地状态，覆盖事务 A 已提交但客户端断线的不确定结果）；进度表补 attempts/last_started_at/last_failed_at/last_error_code 字段；failure_detail 禁止包含完整堆栈/数据库 DSN/供应商密钥/用户正文）；迁移并发认领协议（R21/P1-2：R20 进度表无单实例/认领/重试/接管协议，多迁移进程可能重复处理同一组；修复：KISS 全局单实例——启动先 `pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)` 获取失败立即退出不排队；组级 advisory lock 保留兼作与在线创建路径串行化；每组事务：组级锁 → SELECT progress FOR UPDATE → 锁后重查 status（completed 跳过、仅 pending/failed 认领）；确需多实例并行时升级为带租约认领状态机（running+claim_token/claimed_at/lease_expires_at）单列文档，本版默认不实现）；计费域三层锁序 + 锁内写入顺序（R21/P2-1：R20 “四层锁序”把 LedgerReconciliationAudit INSERT 并列为锁层级易过度泛化——修复：加锁仅三层 ①账户 advisory 锁 → ② run FOR UPDATE → ③ ledger FOR UPDATE（多条按 ledger.id 升序），持锁后按锁内写入顺序执行：ledger 状态更新 → 必要时插入审计（仅人工收敛路径；worker 正常成功转态/confirmed_failed 自动关账/纯 finalizer 重试不插入）→ strict barrier → 置 billing_finalized_at 封口 → settle 事件写入（单次 commit）；§2.9/§2.1/§8.5/验收 83 同步）；DROP INVALID 索引身份校验（R21/P2-2：仅按固定索引名 DROP 有误删风险——修复：DROP 前验证 schema/所属表/索引名/indisvalid=false/indisready/pg_get_indexdef 定义一致后才 `DROP INDEX CONCURRENTLY schema.index_name`（同样不得在事务块内）；同名不同定义的有效索引停止 Contract 转人工；补中断留 INVALID → 识别清理 → 重建 → indisvalid=true → indexdef 一致测试链）；人工收敛无锁预读仅路由（R21/P2-3：R20 预读用途未限制——修复：无锁预读结果仅用于确定锁键与路由，状态/quantity/provider_request_id/run 终态/finalizer 准入/审计字段全部锁后重做；锁后重校验 ledger 存在/run_id 与预读一致/账户与锁键一致/status=manual_reconciliation/finalized IS NULL 五项；ledger.run_id 不可变落数据库约束或 repository 禁止更新入口））
> 上一修订：2026-08-15（R20：吸收第十六轮第三方审查 3 P1 + 2 P2——计费域四层锁序合同（R20/P1-1：R19 锁序只规范到 run 行未纳入 ledger 行——若人工收敛实现为“先按 ledger_id FOR UPDATE 再取账户锁”，与 worker 终态关账（账户+run 锁 → 等 ledger 锁）构成死锁环；修复：扩展为完整四层锁序 ① `pg_advisory_xact_lock(billing_account_user_id)` → ② `ChapterAudioRun` FOR UPDATE → ③ `BillingUsageLedger` FOR UPDATE（多条按 `ledger.id` 升序，禁止无序）→ ④ `LedgerReconciliationAudit` INSERT，禁止式合同：禁止先 run 锁后账户锁、禁止在账户锁与 run 锁之前按 ledger_id 查询或 FOR UPDATE ledger（收敛入口按 ledger_id 以不加锁普通 SELECT 解析所属 run）；作用域界定：约束既有 ledger 行的 UPDATE/FOR UPDATE，建账 INSERT 与审计 INSERT 为新行不构成竞争；补真实 PostgreSQL 双会话测试：worker 终态关账 × 人工收敛同一 ledger，断言无死锁且仅一方成功修改；锁序描述改禁止式表述（R20/P2-2，§2.9/§8.5 同步））；CONCURRENTLY 执行载体与索引时序修正（R20/P1-2：R19 “大表索引 CREATE INDEX CONCURRENTLY”未说明执行载体且合同⑦“已处理组立即受唯一索引保护”不成立——PostgreSQL 不能在事务块内执行 CONCURRENTLY，普通 Alembic revision 默认运行在事务中不能直接替代 `op.create_index()`；全局部分唯一索引只能在全部重复 active 行清理完成后创建，Contract 之前不保护任何组；修复：CONCURRENTLY 必须在 Alembic 事务外专用运维步骤执行或 Alembic 独立 revision `with op.get_context().autocommit_block():` 且不混事务性 DDL；创建前验证 SQL 确认全表无重复 active 组、创建后验证 `pg_index.indisvalid = true`、失败先 DROP INVALID 再重建；维护窗口可接受写入阻塞时可选阻塞式 `CREATE UNIQUE INDEX`；Migrate 期间已处理组由应用层写闸门/advisory 锁保护而非索引，Contract 前不宣称索引保护）；Migrate 版本门禁（R20/P1-3：R19 “允许旧实例运行（读兼容）”与“防止新增重复 active 行”矛盾——advisory 锁串行化只对运行新代码的实例有效，旧版本实例不取新锁仍可全程写重复 active 行，仅“关闭旧重复创建路径”不构成准入；修复：二选一强制构成部署准入——方案 A（推荐）Migrate 前全量滚动部署、确认旧版本实例数为零；方案 B Migrate 窗口对 ChapterAudio 创建/恢复/复制入口加写入闸门（拒绝/排队新增 active 的写操作，闸门日志全程留存）；门禁证据（旧实例数为零/闸门日志）为 Migrate 准入与 Contract 前置条件）；迁移进度专用表（R20/P2-1：R19 “结构化迁移进度记录”未定义持久化位置与原子写入边界——修复：Expand 新建 `audiobook_canonical_migration_progress` 表（组键/canonical 行/source_row_ids/migration_version/status/completed_at/failure_detail，唯一约束 `(migration_version, audiobook_project_id, chapter_id)`），进度标记与单组数据改指/文件登记/校验同事务写入——事务提交后该组才算可跳过；失败组写 failed 与原因不得伪装完成；结构化迁移报告从该表派生单一事实源，不另维护第二份进度来源）；锁序描述改禁止式（R20/P2-2：§2.9/§8.5 原“全部按同一顺序加锁——先 run 行锁后账户锁构成死锁环”句式易误读为“先 run 后账户是合法顺序之一”，改为禁止式：任何路径必须先取账户锁再取 run 锁，禁止反序，完整四层合同见 §2.9））
> 上一修订：2026-08-15（R19：吸收第十五轮第三方审查 1 P0 + 3 P1 + 3 P2——计费域全局锁序统一（R19/P0：R18 worker 主路径"终态 CAS（先锁 run）→ 同事务调 finalizer（后取账户锁）"与 finalizer 固定锁序"账户 advisory 锁 → run 行锁"形成确定死锁环，验收 83 仍宣称"固定锁序无死锁"与主路径实际协议矛盾；修复：worker 终态事务从 `billing_account_user_id`（不可变列，可锁前普通 SELECT 读取）先取账户 advisory 锁，再锁 run、**取锁后重新校验** `status='running' AND claim_token=:token AND billing_finalized_at IS NULL`（禁止使用锁前读取结果）、写终态、清租约、按证据关账并在同一事务执行 finalizer 逻辑单次 commit；worker 建账短事务仅持 run 行锁不取账户锁无锁序反转；补真实 PostgreSQL 双会话测试：会话 A worker 终态主路径 × 会话 B 人工收敛/其他账户 mutation 路径，断言两条路径加锁顺序完全相同且无死锁）；单位合同修正（R19/P1-1：R18 快照示例 `prices[*].unit` 为 `"yuan/second"`/`"yuan/char"`，但 ledger CHECK 只接受 `unit IN ('second','char')` 且要求与 `prices[pricing_key].unit` 一致——按 R18 实现会使全部自动 pending→succeeded 被可结算性校验误拒进 manual_reconciliation；修复：`prices[*].unit` 统一为计量单位 second|char（与 ledger CHECK 同值域），币种由价格字段名 `price_per_second_yuan`/`price_per_char_yuan` 表达，usage_kind → pricing_key → unit 映射与 unit 值域定义为后端唯一常量表（如 billing_unit_constants.py），快照生成/ledger transition service/人工收敛校验/测试四处共用同一来源，禁止重复硬编码）；阶段 1.1 拆 Expand/Migrate/Contract 发布单元（R19/P1-2：R18 把新增/回填字段、canonical 合并、synthetic run、每 run 独立任务切换、部署新版本、drain/cancel 旧任务、施加 NOT NULL/唯一约束全部混入同一个"阶段 1.1"——部署代码与 drain 任务不是 Alembic migration 能完成的步骤，实施者易写出需长停机、依赖 Celery 外部状态、无法可靠回滚的超大迁移；修复：拆为三个独立发布单元，每单元单独写明前置条件、可重复执行规则、数据验证、失败恢复、旧实例兼容、维护窗口、下一步准入条件；Alembic 只做 schema 与数据回填，不得直接操作 broker、执行 Celery revoke、drain/cancel 任务或部署代码——cutover ④⑤均为独立部署步骤）；canonical 合并迁移执行合同（R19/P1-3：R18 合并逻辑方向正确但缺生产可执行性合同——未定义单事务规模、长锁风险、迁移期间防新写重复 active、文件登记与数据库事务失败恢复、幂等断点续跑、索引 CONCURRENTLY、半迁移状态读取；修复：按 `(audiobook_project_id, chapter_id)` 每组一个独立短事务（≤秒级）、结构化进度记录断点续跑、先部署关闭旧重复创建路径或 advisory 锁串行化、单组失败整体回滚、物理文件只登记不搬动、`CREATE INDEX CONCURRENTLY`、读兼容半迁移态、结构化迁移报告为 Contract 准入条件）；snapshot_status 去 server_default（R19/P2-1：R18 `server_default="frozen"` 会使历史行在无快照时被误标 frozen，立即违反 frozen→snapshot 非空 CHECK 或产生错误语义；修复：迁移顺序改为新增可空列（无默认）→ 按证据回填 → 校验非法组合 → 置 NOT NULL + 三态 CHECK，新记录由应用服务显式写 frozen）；审计表数据库级 append-only（R19/P2-2：R18 仅靠 repository/service 层无 update/delete 入口，无法防止新代码直接 session 修改、管理脚本 UPDATE/DELETE、误加 repository 更新方法、数据库账户本身拥有表更新权限；修复：叠加数据库级强制保护——BEFORE UPDATE OR DELETE trigger → RAISE EXCEPTION（或对应用角色仅授 SELECT/INSERT），测试直接执行 SQL 验证数据库拒绝修改删除）；文档拆分路线图（R19/P2-3：本文档已演化为全系统计费与任务平台改造，超出单一功能指南合理变更面——正式实施前必须拆为至少四份可独立验收的设计：①双引擎配置、批次和快照隔离 ②场景 revision、编辑器及发布模型 ③run 派发、worker lease 和恢复协议 ④计费 ledger、账户 mutation service 和 finalizer，主文档只保留依赖关系与跨文档不变量））
> 上一修订：2026-08-14（R18：吸收第十四轮第三方审查 1 P0 + 3 P1 + 4 P2——finalizer 触发协议与主路径（R18/P0：R17 只定义 finalizer 前置条件、未定义触发路径——worker 完成时握有效租约致前置永不满足、租约过期后无重试机制、全部 ledger 已 succeeded 时收敛入口进不去，成功跑完的 run 冻结会永久挂死；修复：写执行终态的同一条 CAS 清租约（`claim_token/claimed_at/lease_expires_at=NULL`）+ 同事务立即调 finalizer（正常成功当场结算并释放冻结），beat 扫描器 `billing_finalizer_scan` 定期重试“终态 ∧ 未封口 ∧ 无有效租约”（run 行本身即结算意图记录，不引入新表），取消/失败按证据关账本 run 全部 pending（无供应商证据 → confirmed_failed、已发出或结果不明 → manual_reconciliation，不得残留 pending 否则 barrier 永远过不了），建账谓词补上执行状态与当前租约 token（`status='running' AND claim_token=:token AND billing_finalized_at IS NULL`））；审计单调 CHECK 改 rank 编码（R18/P1-1：R17 硬编码 succeeded 时 new_commit_stage='post_call'，与“原记录已 result_persisted 保持不变”的收敛语义冲突、验收 80 断言一跑就撞 CHECK——改为 pre_call=1 < post_call=2 < result_persisted=3 单调不减）；建账合同改独立短事务锁当前租约（R18/P1-2：R17“与首次认领 CAS 同一事务”令同 run 多次 TTS/ASR/remix 调用要么整段握长事务、要么提交 pending 时丢失 run 锁，“settle 在先、ledger 在后”会回来）；pricing_key 映射表（R18/P1-3：prices 键 seed_scene/tts/asr 与 usage_kind seed_render/tts_chars/asr_seconds/remix 无映射且无 remix 价格条目，chapter_remix 会全部掉进人工对账——prices 补 remix 条目，usage_kind → pricing_key → prices 键 → unit 映射作为可结算性验证唯一依据，修正“pricing_key = provider+model 组合”表述为用量维度键）；P2：清除“等最后一条收敛时完成 settle”残留（改统一 finalizer 在 run 终态后结算）、ChapterAudioRun 测试清单补 billing_finalized_at/billing_account_user_id、澄清账户 advisory 锁（全局顶层）与 ChapterAudio FOR UPDATE（业务行锁域第一步）锁序域矛盾、数据库 trigger 保障 billing_finalized_at/billing_account_user_id 不可变（R17 仅应用层承诺））
> 上一修订：2026-08-14（R17：吸收第十三轮第三方审查 1 P0 + 4 P1——run 计费封口与结算并发协议（R17/P0：strict barrier 只检查已有 ledger、不阻止 worker 结算后新增 pending ledger——账户锁无法覆盖 worker 的 ledger 写入路径，settle 后新产生的费用无法补扣且禁止 supplement/二次 settle，形成永久少扣费；新增 run 级计费封口协议：`ChapterAudioRun.billing_finalized_at` 持久化封口、统一 finalizer 单事务（账户锁 → run FOR UPDATE → 校验执行终态/无有效 lease/全部 ledger 终态 → 置封口 → 唯一 settle → 单次 commit）、worker 每次新建 ledger attempt 前必须锁 run 并拒绝已 finalized 的 run（租约认领 CAS 加 `billing_finalized_at IS NULL` 前置）、run 未终态时人工收敛只提交 ledger 与审计不立即 settle、真实 PostgreSQL 双会话测试断言不可能出现“settle 在先、ledger 在后”）；人工收敛证据单调性与恢复证据不可变（R17/P1-1：CAS 不再无条件覆盖——commit_stage 仅允许从 pre_call 推进到 post_call（result_persisted 不倒退）、provider_request_id 仅允许 NULL 补齐（已有值时新值必须为空或一致否则 409/422）、成功收敛写 recovery_method='manual'、审计表结构化记录原/新 provider_request_id 与 commit_stage）；父任务矩阵改计数穷尽规则（R17/P1-2：{cancelled, failed} 此前无定义结果——第③条前置成立但既非全 cancelled 也无成功项、第④条“否则”不继续；改为 unknown → failed+审计、任一进行中 → running、全 succeeded → completed、全 cancelled → cancelled、至少一 succeeded 且存在失败/取消 → completed_with_partial_failure、无 succeeded 且至少一 failed → failed，补 {cancelled, failed} 与 {cancelled, failed, succeeded} 测试）；计费账户权威来源（R17/P1-3：BillingUsageLedger 无计费账户字段、当前代码从 Project.user_id 推导而冻结事实存 AdminOperationLog.resource_id——项目归属变化会锁错账户；新增 `ChapterAudioRun.billing_account_user_id` 不可变列并纳入 run_input_snapshot.billing_context，人工收敛锁键取自该字段并强制校验 active freeze 的 resource_id/billing_key/run_id 一致，补“冻结后项目所有者变化仍结算原账户”测试）；succeeded 可结算性数据库约束（R17/P1-4：pricing_key/billing_snapshot_id 可 NULL、unit 注释有 CHECK 实际没有、worker 自动路径无可定价性校验——succeeded CHECK 收紧为同时具备 quantity>0/pricing_key/billing_snapshot_id、新增 unit 值域 CHECK、全部成功转态复用统一 ledger transition service 做可定价性校验、历史不可验证 succeeded 记录显式转 manual_reconciliation 拒绝结算而非 NULL 静默放行））
> 适用范围：有声书生成配置页（`legacy_stems` 分轨合成 / `seed_scene` 场景生成双引擎）
> 基线文档：`docs/AUDIOBOOK_SEED_AUDIO_SCENE_DIRECTOR_V2_IMPLEMENTATION_GUIDE_20260807.md`
> 相关文档：`docs/AUDIOBOOK_SINGLE_SEGMENT_WORKBENCH_IMPLEMENTATION_GUIDE.md`

## 0. 变更历史（简短记录；完整修订说明见各版本摘要）

- **R22（审查修订版 21，2026-08-15，第十八轮审查 3 P1 + 1 补充建议）**：进度表状态值域与认领协议一致性（方案 A：本版仅全局单实例，status 保留 pending/completed/failed 三态，删除默认合同中 running/租约/接管死分支；多实例升级备注明确届时同步扩展 CHECK 值域）；事务 B fail-closed 防覆盖 completed（`ON CONFLICT DO UPDATE ... WHERE status <> 'completed'`；提交结果不确定时先新连接重读 progress，completed 且一致性校验通过视为成功绝不写 failed；补真实 PostgreSQL 断线测试：不得把 completed 改为 failed、不重复创建 synthetic run/output/文件登记）；会话锁专用连接与解锁合同（专用非池化连接持有、获取失败立即关闭退出、finally `pg_advisory_unlock` 后关闭、不归还连接池、进程崩溃断连释放并记录 run_id/host/pid、运维检查 SQL 人工确认后才 terminate 禁止自动 kill；补异常退出/进程死亡双场景测试）；attempts 仅确认失败并写入事务 B 时递增（不确定成功组不递增，避免迁移报告误计失败历史）。
- **R21（审查修订版 20，2026-08-15，第十七轮审查 2 P1 + 3 P2）**：迁移失败记录事务边界（事务 A 组处理——仅 completed 与业务数据同事务提交才可跳过；事务 A 回滚后独立短事务 B 写 failed + 脱敏 failure_detail + attempts/last_failed_at/last_error_code；重试先读进度表 completed 并重跑组级一致性校验后跳过，覆盖提交后断线的不确定结果；进度表补 attempts/last_started_at/last_failed_at/last_error_code）；迁移并发认领协议（KISS 全局单实例 `pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)` 获取失败立即退出；组级 advisory lock 保留兼与在线创建路径串行化；每组事务组级锁 → progress FOR UPDATE → 锁后重查 status；多实例并行需升级为带租约认领状态机单列文档）；三层锁序 + 锁内写入顺序（加锁仅账户 → run → ledger（按 id 升序）三层；锁内写入：ledger 更新 → 必要时审计 INSERT（仅人工收敛）→ barrier → 封口 → settle；audit 不是锁层级，§2.9/§2.1/§8.5/验收 83 同步）；DROP INVALID 索引身份校验（schema/表/索引名/indisvalid/indisready/pg_get_indexdef 定义一致后才 DROP INDEX CONCURRENTLY；同名不同定义的有效索引停止 Contract；补测试链）；人工收敛无锁预读仅路由（安全判断全部锁后重做；锁后五项重校验；ledger.run_id 不可变落数据库约束/repository 禁更新）。
- **R20（审查修订版 19，2026-08-15，第十六轮审查 3 P1 + 2 P2）**：计费域四层锁序合同（账户 advisory 锁 → run FOR UPDATE → ledger FOR UPDATE（多条按 `ledger.id` 升序）→ 审计 INSERT；禁止先 run 锁后账户锁、禁止在账户锁/run 锁前按 ledger_id 锁 ledger；收敛入口按 ledger_id 不加锁 SELECT 解析所属 run；作用域：既有 ledger 行的 UPDATE/FOR UPDATE；补同 ledger 双会话测试 + 代码级检查项）；CONCURRENTLY 执行载体与索引时序（事务块内不可执行；Alembic 事务外专用运维步骤或独立 revision `autocommit_block()`；建前验证 SQL 全表无重复 active、建后 `indisvalid=true`、失败 DROP INVALID 重建；维护窗口备选阻塞式 `CREATE UNIQUE INDEX`；R19 ⑦“已处理组立即受唯一索引保护”不成立——全局索引只能在全部重复清理后创建，Migrate 期间已处理组由写闸门/advisory 锁保护）；Migrate 版本门禁（方案 A 全量滚动部署旧实例为零（推荐）/方案 B 写闸门拒绝新增 active 写操作，二选一强制构成准入；advisory 锁只对新代码实例有效，仅“关闭旧路径”不构成准入；门禁证据为 Migrate 准入与 Contract 前置）；迁移进度专用表（Expand 建 `audiobook_canonical_migration_progress`，进度标记与单组改指/文件登记/校验同事务提交才可跳过，失败组 failed 带原因不伪装完成，报告从该表派生单一事实源）；锁序描述改禁止式（§2.9/§8.5 同步，消除“先 run 后账户”误读）。
- **R19（审查修订版 18，2026-08-15，第十五轮审查 1 P0 + 3 P1 + 3 P2）**：计费域全局锁序统一（worker 终态事务先取账户 advisory 锁 → run FOR UPDATE → 取锁后重校验 status/claim_token/封口 → 终态 CAS 清租约 → 关账 → 同事务 finalizer 单次 commit，消除 R18 "run 行锁 → 账户锁"死锁环；补双会话测试：worker 终态 × 人工收敛同锁序验证）；单位合同修正（prices[*].unit 统一计量单位 second|char，币种由价格字段名表达，usage_kind → pricing_key → unit 唯一常量表四处同源）；阶段 1.1 拆 Expand/Migrate/Contract 发布单元（每单元前置/幂等/验证/回滚/旧实例兼容/维护窗口/准入条件；Alembic 不操作 broker、不 revoke、不部署代码，cutover ④⑤独立部署步骤）；canonical 合并执行合同（逐组短事务 ≤秒级 + 断点续跑 + 防新写重复 active + 物理文件只登记 + CONCURRENTLY + 结构化报告为 Contract 准入）；snapshot_status 去 server_default（可空列 → 回填 → 校验 → NOT NULL，应用服务显式写 frozen）；审计表数据库级 append-only（BEFORE UPDATE OR DELETE trigger → RAISE EXCEPTION，SQL 级测试验证拒绝修改删除）；文档拆分路线图（四份可独立验收设计，主文档只留依赖关系与跨文档不变量）。
- **R18（审查修订版 17，2026-08-14，第十四轮审查 1 P0 + 3 P1 + 4 P2）**：finalizer 触发协议与主路径（终态 CAS 清租约 + 同事务立即调 finalizer + beat 扫描兜底 + 取消/失败按证据关账 + 建账谓词校验执行状态/当前租约/封口三要素）；审计单调 CHECK 改 rank 编码（pre_call=1 < post_call=2 < result_persisted=3，R17 硬编码 post_call 撞 result_persisted 收敛语义）；建账改独立短事务锁当前租约（R17 绑首次认领致长事务或丢锁）；pricing_key ↔ usage_kind ↔ prices 键 ↔ unit 映射表（prices 补 remix 条目）；P2 四处（“最后收敛 settle”残留、测试清单补计费封口字段、锁序域澄清、不可变数据库 trigger）。
- **R17（审查修订版 16，2026-08-14，第十三轮审查 1 P0 + 4 P1）**：run 计费封口协议（billing_finalized_at + 统一 finalizer + worker 锁 run 拒绝 finalized + 人工收敛未终态不 settle）；人工收敛证据单调（commit_stage 仅 pre_call→post_call、provider_request_id 仅 NULL 补齐、recovery_method='manual'、审计结构化证据）；父任务矩阵改计数穷尽规则（{cancelled, failed} → failed）；计费账户权威来源（billing_account_user_id 不可变列 + freeze 一致性校验）；succeeded 可结算性约束（CHECK 收紧 + unit CHECK + 统一 transition service + 历史不可验证转 manual_reconciliation）。
- **R16（审查修订版 15，2026-08-14，第十二轮审查 1 P0 + 2 P1 + 2 P2）**：人工收敛请求模型按目标状态区分（succeeded 强制 quantity>0 + commit_stage 推进 post_call + snapshot 计价字段匹配校验；confirmed_failed 不带未确认用量）；人工收敛全链路单事务原子化（锁 → 校验 → CAS → 审计 → barrier → settle → 单次 commit）；六步流程统一引用 §1.1 正式矩阵；execution_status 投影补 expired/pause_requested；ledger_reconciliation_audits 完整约束模型 + append-only 合同。
- **R15（审查修订版 14，2026-08-13，第十一轮审查 2 P0 + 4 P1）**：run 状态 CHECK 补 expired；settle 索引改 resource_id 账户作用域 + dedupe_superseded 退出谓词；聚合矩阵 unknown 置顶；子派发表无 celery_task_id；前端穷举映射；人工收敛写路径初版。
- **R14（审查修订版 13，2026-08-13，第十轮审查 1 P0 + 5 P1）**：ledger DDL 可执行性（provider_request_id 统一、status String(32)）；子派发表删除 celery_task_id；父 CHECK 两阶段收窄；normalize fail-closed；dispatcher token fencing；settle 幂等键数据合同。

## 1. 文档定位

当前有声书配置页左侧有两个卡片区域：上部"章节队列"（章节选择与生成状态）、下部"叙事与音频"（生成引擎选择、输出格式、音效与配乐）。右侧为"角色声音"配置区。

两种生成引擎对应两种完全不同的生成模式：

- `legacy_stems`（分轨合成）：逐句 TTS + 分轨混音，用户配置音效/配乐参数。
- `seed_scene`（场景生成）：Seed Audio 场景导演整段渲染，音效/配乐由生成过程决定，用户不配置音效参数。

当前实现存在以下结构性缺陷：

1. **角色音色绑定共享同一命名空间**：`Project.audio_config.characters` 为全局一份，切换引擎后同一角色名在不同引擎下的 `voice_id`/`reference_source` 互相覆盖。
2. **章节生成状态无引擎维度**：`resolveGeneratedChapterIdsFromProjects` 跨所有历史批次合并 `ChapterAudio`，`seed_scene` 生成的章节在 `legacy_stems` 下仍显示"已生成"，与"从未生成过"语义冲突。
3. **章节编辑器单一**：点击已生成章节统一进入剧本编辑器，无法区分章节归属引擎，场景生成章节缺少场景化工作台。
4. **引擎选择位置与语义不匹配**：生成引擎是决定整章生成方式的首要开关，却位于第二张卡片中，且与分轨模式的音效配置强绑定。
5. **生成编排未按引擎分流**：无论模式都先执行 `AudioDirector.formulate_strategy()` 并应用音效/配乐密度策略，`seed_scene` 模式继承了旧导演的行为取向；`SoundEffectDesigner`/`MusicComposer` 仍可能在 `seed_scene` 模式被非预期调用。
6. **运行链路实时读取可变配置**：后台生成、恢复、计费预检、结算每次从 `Project.audio_config` 实时解析模式、音色与 audio_fx（`project_audio_runtime.resolve_project_audio_runtime_config`、`background_jobs_full._apply_project_audio_effects`、`task_support.resolve_audiobook_billing_pricing_context`、`routes_recover`/`routes_subtitle`/`routes_segment_regen` 等），批次创建后用户切换引擎会导致"任务按 A 计费、按 B 执行"。
7. **API 合约未覆盖引擎分支**：`ProjectAudioConfig` Pydantic 模型仅含顶层 `characters`/`audio_fx`/`audio_engine_mode`/`seed_audio_model`，前端提交 `engines` 会被忽略；GET/PUT 端点与自动分配音色接口（`POST /{project_id}/audio-config/auto-voices`）只读写顶层结构。
8. **章节渲染状态无持久化与投影**：`seed_scene` 的"全部场景 passed / 含回退 / 人工评审 / 过期"无独立字段承载；批次列表接口不返回 `engine_mode` 与渲染状态，前端只能消费 `generatedChapterIds: Set<number>` 二值集合。
9. **场景试听无资产落点**：场景音频写在任务运行目录（`data/audiobook_scene_runs/{task_id}/...`），无正式 artifact 登记与场景级授权端点，任务结束后试听可能失效。

本文档定义双引擎彻底隔离的目标架构与实施阶段，包括**外围数据隔离**和**核心生成过程隔离**两个层面，是本次改造的当前实施事实源。

**文档拆分路线图（R19/P2-3，第十五轮审查）**：本文档实际已演化为"全系统计费与任务平台改造"（积分 mutation service 收敛、拆书/小说协同/短剧/管理员调账、Celery 父子任务模型、run-as-outbox dispatcher、worker lease 与 provider 恢复、ledger 人工对账、settle 唯一索引与历史账单清洗、文件生命周期管理），显著超出"双引擎隔离与场景编辑器"单一功能指南的合理变更面，不得作为单一项目阶段整体实施。正式实施前必须拆为**至少四份可独立验收的设计文档**，各自独立上线、独立回滚、独立压测：

1. **双引擎配置、批次和快照隔离**（本文档 §1/§2.1 核心：engine_mode、批次级快照、历史回填与三态 snapshot_status）；
2. **场景 revision、编辑器及发布模型**（§2.9 revision/head 双表、§2.4 双指针发布、场景工作台）；
3. **run 派发、worker lease 和恢复协议**（§2.1 六步第 4 步 outbox、dispatcher 租约认领、§8 provider 恢复与 claim/lease/fencing）；
4. **计费 ledger、账户 mutation service 和 finalizer**（§8.5 统一 finalizer、§1.4 points mutation service 收敛、人工对账与审计）。

拆分后本主文档只保留**依赖关系与跨文档不变量**（全局锁序、事务所有权、封口 barrier、单位常量表同源），并清除历史版本残留描述；各子文档引用本主文档的不变量条款，不得各自复制冲突版本。拆分完成前，本文档继续作为唯一事实源，实施排期必须按上述四域分别立项。

## 2. 已确认决策

### 2.1 引擎维度 = 批次维度（冻结、迁移与复用规则）

`AudiobookProject`（生成批次）增加 `engine_mode` 列，`ChapterAudio` 通过关联批次自然获得引擎维度，子表不重复加列。同一章节在两引擎下各有一条独立批次记录，互不覆盖、互不干扰。

```python
# backend/app/models/audiobook.py（经 Alembic 迁移，非仅模型声明）
class AudiobookProject(Base):
    ...
    engine_mode = Column(
        String(20),
        nullable=False,
        server_default="legacy_stems",  # 数据库默认值只作用于新插入行；已有行必须显式 UPDATE 回填
        index=True,
    )
    # 批次创建时冻结的引擎配置快照（规范化值 + 源配置 hash），运行期只读
    # 批次创建时冻结的引擎配置快照（规范化 payload + 审计元数据分离）
    engine_config_snapshot = Column(Text, nullable=True)
    # 快照规范化指纹（仅业务标识字段参与 hash），供批次复用判定
    engine_config_fingerprint = Column(String(64), nullable=True, index=True)
    # 快照状态：
    #   frozen（正常，有批次级 checkpoint/运行参数/账单事实证明输入）
    #   legacy_unfrozen（历史批次快照无法可靠生成，禁止恢复）
    #   legacy_unverified（历史批次快照从当前可变配置推导或无引擎证据，不保证代表真实历史输入，仅展示与审计，禁止恢复）
    # R19/P2-1：不设 server_default——历史行按证据回填，新记录由应用服务显式写 frozen；
    # 绕过应用服务且不带 snapshot 的插入因无默认值而 NOT NULL 失败，不会误标 frozen（迁移顺序见 §1.1）
    snapshot_status = Column(String(20), nullable=False)
    # __table_args__ 增加 CHECK 约束（数据库层杜绝非法状态）：
    #   snapshot_status IN ('frozen','legacy_unfrozen','legacy_unverified')（三态值域 CHECK，R8）
    #   (snapshot_status = 'frozen') → engine_config_snapshot IS NOT NULL
    #   (snapshot_status = 'legacy_unfrozen') → engine_config_snapshot IS NULL
    #   （legacy_unverified 允许推导快照或 null，均禁止恢复；三态空值约束与验收标准 12 统一，R8）
```

**约束与迁移规则：**

- **必须提供 Alembic 迁移脚本**（SQLAlchemy `Column(default=...)` 只作用于 Python 侧新建对象，已有数据库行仍是 NULL，后续 `WHERE engine_mode = 'legacy_stems'` 会排除全部旧批次）。迁移顺序：新增可空列 → **一次性完成引擎证据判定后直接写最终值**（不经过"先全量回填 `legacy_stems`"的中间步骤——历史行按下文"引擎推断"逐批次直接写 `legacy_stems`/`seed_scene` 终值，一次 UPDATE 完成，避免中间态被误读）→ 置 `NOT NULL` + `server_default` → 加 CHECK 约束（值域仅 `legacy_stems`/`seed_scene`）→ 建立 `(project_id, engine_mode, deleted_at)` 组合索引（章节状态查询按引擎过滤走该索引）。
- `engine_mode` 值域**不含 `auto`**。API 接受的 `"auto"`（`projects.py` Pydantic 合约）必须在创建批次前解析为确定值（见 §2.4 归一化规则），冻结后的批次列只保存 `legacy_stems`/`seed_scene`。
- 旧数据（无 `engine_mode` 的历史批次）经迁移按下文"引擎推断"逐批次回填（`seed_scene` 为后引入引擎）；**无引擎证据的批次不得回填为可恢复的 `legacy_stems`**。

**历史批次的快照策略（P0 闭环，不允许"只回填引擎列、快照留空"）：**

- **引擎推断**：不能简单按"无 `engine_mode` 列"统一回填 `legacy_stems`。当前数据库中可能已存在 Seed 运行（`project_audio_config.py` 已定义 `AUDIO_ENGINE_MODES = {"legacy_stems", "seed_scene", "auto"}`、`checkpoint_contracts.py` 已定义 `SEED_SCENE_CHECKPOINT_TYPE`、`_scene_render_mixin.py` 已按 `seed_scene` 分支运行）。迁移必须按以下证据逐批次推断：
  1. `ChapterAudioRun.checkpoint_json` 中的 `checkpoint_type` 或 `stats.mode` 含 seed 标记
  2. `scene_audio_artifacts`（如果已有）或 `scene_checkpoints` 存在
  3. 任务运行参数含 `seed_audio_model`
  4. Seed provider attempt / billing 记录
  以上任一命中 → 回填 `seed_scene`；全未命中 → `legacy_stems`。
- **引擎证据不足的批次禁止声明为可恢复的 legacy**：只有**批次级 checkpoint、运行参数或账单事实能证明真实输入**的批次才允许 `snapshot_status = 'frozen'`。当前 `Project.audio_config` 的旧顶层数据（`tts_models`/`characters`/`audio_fx`）始终属于**推导值**，不能单独证明某个历史批次的真实输入——引擎证据不足、快照只能从当前可变配置推导的批次统一标记 `legacy_unverified` 并**禁止恢复**（恢复入口报错"历史批次配置不可用，请重新生成"），不允许按 legacy_stems 恢复执行。
- **快照生成优先级**：
  1. 可验证的历史输入（从 `ChapterAudioRun.checkpoint_json`/运行参数/billing 记录解析，可证明真实输入）写入 `engine_config_snapshot`，`snapshot_status = 'frozen'`。
  2. 只能从当前 `Project.audio_config`（可变）推导的补充字段写入快照，`snapshot_status = 'legacy_unverified'`（仅允许展示与审计，**不允许恢复/重算/宣称代表真实历史输入**）。
  3. 解析失败（JSON 损坏等）的批次：`snapshot_status = 'legacy_unfrozen'`，**禁止恢复/续跑**（恢复入口直接报错"历史批次配置不可用，请重新生成"），不允许静默使用实时配置。
- **`engine_config_snapshot` 结构（审计元数据与业务标识分离）：**

```jsonc
{
  // === 业务标识字段（参与 engine_config_fingerprint hash） ===
  "snapshot_version": 2,
  "engine_mode": "legacy_stems",
  "engine_branch_config": {
    "seed_audio_model": "seed-audio-1.0-multilingual",  // 规范化模型 ID；仅 seed_scene 非空，legacy_stems 为 null
    "providers": {                                      // 冻结的供应商组合（各自由生成链路冻结时的规范化值）
      "seed_provider": "dashscope_seed",
      "asr_provider": "dashscope_asr",
      "fallback_tts_model": "qwen3-tts-instruct-flash",
      "fallback_tts_provider": "dashscope"
    },
    "tts_models": {
      "qwen3-tts-instruct-flash": {
        "characters": [
          {"character_id": 1, "name": "旁白", "voice_id": "Neil", "tts_model": "qwen3-tts-instruct-flash"}
        ]
      }
    },
    "audio_fx": {"enable_sound_effects": true, "enable_music": true}
  },
  // === 纯审计元数据（不参与 hash，不影响批次复用判定与运行输入签名） ===
  "captured_at": "2026-08-12T10:00:00Z",
  "source_audio_config_hash": "sha256:...",
  "migrated_at": null
}
```

- `engine_config_fingerprint = sha256(canonical_json({snapshot_version, engine_mode, engine_branch_config}))` —— 只有业务标识字段参与 hash，**`engine_branch_config` 含 `seed_audio_model` 与 `providers` 组合**（`seed_audio_model` 或任一供应商/回退模型不同即产生不同 fingerprint，避免 `seed-audio-1.0` 与 `seed-audio-1.0-multilingual` 复用同一批次）。`captured_at`、`source_audio_config_hash`、`migrated_at` 等审计元数据不参与，确保相同配置产生相同的 fingerprint。
- `source_audio_config_hash` 仅用于审计"配置在批次创建后被改动过"（记录 `Project.audio_config` 在快照捕获时刻的 hash），**不作为运行输入**：配置被改动不影响恢复/续跑（恢复消费 `run_input_snapshot`，见下）。**不允许从当前配置反向补全快照**（避免伪造历史运行输入）。

**配置快照（引擎"冻结"的运行期载体）：**

批次创建时（入队成功点）解析出确定的 `engine_mode`，并将不可变快照写入 `AudiobookProject.engine_config_snapshot`。**后台生成、暂停恢复、场景重渲染一律只消费该快照（引擎配置部分）**，不读 `Project.audio_config` 实时值；**计费预检、冻结与结算消费同一个不可变 `billing_snapshot`（R8 捕获顺序见下"计费快照捕获顺序与作用域"：预检在捕获之后、run 创建之前，结算消费 run 快照内嵌的同一 snapshot）**。`source_audio_config_hash` 仅用于审计"配置在批次创建后被改动过"，不作为运行输入。

**运行输入快照（run_input_snapshot，每次运行独立，方案 A：自包含内嵌正文）：**

批次快照是"引擎分支基线"，每次**新运行**（`ChapterAudioRun` 创建）必须再冻结一份 `run_input_snapshot`。**方案 A（已选定）**：快照内嵌恢复所需的全部正文（引擎配置 payload、剧本事实、音色解析结果、编辑基线投影、运行参数、策略与计费），hash 仅用于校验不用于重建输入。恢复任务**只消费本快照**，不读 `Project.audio_config`、`engine_config_snapshot`、`ChapterAudio.script_json` 实时值。

**快照合同按 `run_type` 分界（R7 修正，解决"捕获边界自相矛盾"）**——"禁止读取实时数据"仅约束**运行执行与恢复阶段**，不禁止新运行创建阶段的快照捕获：

- `script_only`/`full`：运行创建时**尚无剧本**（full 的剧本由后台生成并在运行中才写回 `script_json`，`background_jobs_full.py` 约 400 行），快照冻结**原章输入**（章节 `content` 正文）、引擎配置、运行参数与计费；`script_facts`/`voice_resolution`/`revision_projection` 为 `null`，此类运行的恢复不消费剧本事实与音色解析事实（**依赖 checkpoint——R9 派生执行事实，R10 分阶段冻结 P1-2**：full 运行按阶段完成后分别冻结 `derived_execution_facts` 子项为不可变 checkpoint——剧本生成完成后冻结 `generated_script_facts`（+ `generated_script_facts_hash`，与 `script_facts` 同构）、voice_binding 完成后冻结 `voice_resolution`（+ `voice_resolution_hash`）、scene_planning 完成后冻结 `scene_topology`（+ `scene_topology_hash`），冻结过的子项不可覆盖；失败于某阶段后的恢复从最后一个完整阶段的下一阶段继续——不重新调用非确定性剧本生成/音色解析过程、不读 `ChapterAudio.script_json`/`Project.audio_config` 实时值，§2.11）。
- `audio_from_scripts`/场景重渲染：运行创建时剧本已存在（`script_status='approved'`），在**创建运行的同一事务中**读取当前已审批 `script_json` 正文与 revision heads 投影并立即冻结（读一次、立即内嵌，事务提交后不再读）；后续执行/恢复只消费快照正文。
- 运行创建后、执行与恢复期间，任何路径不得重新读取 `Project.audio_config`/`ChapterAudio.script_json`/`engine_config_snapshot` 构造输入（§2.11）。

快照结构（方案 A）：

```jsonc
run_input_snapshot = {
  // === 批次基线（引用，仅审计与关联用，不参与输入重建） ===
  "engine_mode": "<批次 engine_mode>",
  "base_fingerprint": "<批次 engine_config_fingerprint>",
  "batch_snapshot_version": "<engine_config_snapshot.snapshot_version>",

  // === 引擎配置正文（内嵌 engine_branch_config，含 seed_audio_model 与 providers 组合） ===
  "engine_config_payload": { ...engine_config_snapshot.engine_branch_config 完整正文... },

  // === 剧本事实正文（按 run_type 冻结） ===
  //   audio_from_scripts/场景重渲染：创建运行同一事务内读已审批 script_json 正文
  //   script_only/full：null（运行中生成，恢复依赖 checkpoint 的 derived_execution_facts）
  "script_facts": [
    {"segment_key": "seg_a1b2c3", "speaker": "旁白", "text": "...", "seq": 1}, ...
  ] | null,
  "script_facts_hash": "sha256(canonical_json(script_facts))" | null,

  // === 原章输入正文（script_only/full 冻结章节 content；audio_from_scripts/重渲染为 null，以 script_facts 为准） ===
  "source_chapter_content": "<章节 content 正文> | null",

  // === 角色音色解析结果正文（按 run_type 冻结） ===
  //   audio_from_scripts/场景重渲染：创建运行同一事务内解析并内嵌（读一次即冻结）
  //   script_only/full：null（音色解析在剧本生成后执行，运行中派生——恢复依赖
  //     checkpoint 的 derived_execution_facts.voice_resolution，§2.11/R9）
  "voice_resolution": [
    {"character_id": 1, "name": "旁白", "voice_id": "Neil", "reference_source": null, ...}, ...
  ] | null,
  "voice_resolution_hash": "sha256(canonical_json(voice_resolution))" | null,

  // === 运行参数（完整嵌入，来自现有生成接口的实际输入） ===
  "run_options": {
    "tts_model": "<normalized tts_model>",
    "output_format": "mp3",
    "narration_style": "<style> | null",
    "narration_style_prompt": "<prompt> | null",
    "generate_subtitle": true,
    "timeline_edits": {<chapter_id>: {<segment_key>: {"speed": 1.0}}}
  },

  // === 策略与计费（完整嵌入，含供应商组合与不可变计价事实） ===
  "billing_context": {
    "provider": "<TTS provider>",
    "seed_provider": "<Seed provider>",
    "asr_provider": "<ASR provider>",
    "fallback_tts_model": "<fallback TTS 模型> | null",
    "fallback_tts_provider": "<fallback TTS provider> | null",
    "fallback_policy": "<policy>",
    "billing_rules_version": "<version>",
    "billing_account_user_id": "<Integer>  // 不可变计费账户（R17/P1-3）：创建 run 时从冻结事务的目标账户写入（与冻结同一事务），运行期不随 Project.user_id 变化；人工收敛锁键与 finalizer 账户锁的唯一权威来源，禁止从当前 Project.user_id 推导（冻结事实在 AdminOperationLog.resource_id）",
    // 不可变计价事实（自包含；预检/冻结/结算只消费本快照，
    // 定价规则或账户层级变化后仍按本快照结算，§8.5）
    "billing_snapshot": {   // 不可变计价事实（R8：字段直接对齐 PointsPricingPolicyConfig / PointsBusinessSettlementSnapshot
                            // 实际计费模型——user_tier_multiplier + discount_rate 近似字段无法无损重放真实结算公式，
                            // 见 points_pricing_policy.py 约 115/310 行；禁止另发明一套近似字段）
      "snapshot_id": "<唯一 ID，审计关联>",
      "captured_at": "<ISO 时间>",
      "prices": {   // 各 provider/model 供应商目录价（业务输入，捕获时刻值）；unit 仅为计量单位（second|char，与 ledger.unit 同值域，
                    // R19/P1-1：不再混入价格表达单位——R18 示例 "yuan/second" 与 ledger CHECK 值域 'second'/'char' 不等，
                    // 按 R18 实现会使全部自动 pending→succeeded 被“unit 一致”校验拒绝进 manual_reconciliation），
                    // 币种由价格字段名表达（price_per_second_yuan/price_per_char_yuan）
        "seed_scene": {"provider": "dashscope_seed", "model": "seed-audio-1.0-multilingual", "price_per_second_yuan": 0.0, "unit": "second"},
        "tts": {"provider": "dashscope", "model": "qwen3-tts-instruct-flash", "price_per_char_yuan": 0.0, "unit": "char"},
        "asr": {"provider": "dashscope_asr", "model": "<asr model>", "price_per_second_yuan": 0.0, "unit": "second"},
        "remix": {"provider": "<remix provider>", "model": "<remix model>", "price_per_second_yuan": 0.0, "unit": "second"}  // R18/P1-3：chapter_remix 按重混用量计费（见 §2.10 run_type 表），必须有独立价格条目
      },
      // pricing_key ↔ usage_kind ↔ prices 键 ↔ unit 映射（R18/P1-3，统一 ledger transition service 可结算性验证的唯一依据——R17 要求 pricing_key ∈ prices 但未定义映射）：
      //   seed_render → seed_scene → second ｜ tts_chars → tts → char ｜ asr_seconds → asr → second ｜ remix → remix → second
      // pricing_key 为用量维度键（非 provider+model 组合——provider/model 位于 prices[pricing_key] 值结构内部）；验证规则：pricing_key ∈ prices 且 prices[pricing_key].unit 与 ledger.unit 一致
      // **唯一常量表（R19/P1-1）**：上述 usage_kind → pricing_key → unit 映射与 unit 值域（second|char）定义为后端唯一常量表
      // （如 billing_unit_constants.py），快照生成、统一 ledger transition service、人工收敛校验与测试共用同一来源，
      // 禁止四处重复硬编码（测试断言四处引用同一常量表）
      "points_per_yuan": 0.0,                // 积分换算（对齐 POINTS_POLICY_POINTS_PER_YUAN，捕获时刻值）
      "user_price_basis": "public_list_price",  // 计价基准（对齐 POINTS_POLICY_USER_PRICE_BASIS）
      "user_price_rate": 1.0,                // 用户价格倍率（对齐 POINTS_POLICY_USER_PRICE_RATE）
      "provider_discount_capture_rate": 0.0, // 供应商折扣捕获率（对齐 POINTS_POLICY_PROVIDER_DISCOUNT_CAPTURE_RATE）
      "provider_discount_rate": 0.0,         // 供应商折扣率（resolve_provider_discount_rate 结果）
      "provider_discount_source": "<env:...|provider_catalog|default>",  // 折扣来源（审计）
      "freeze_buffer_rate": 0.0,             // 冻结缓冲率（对齐 POINTS_POLICY_FREEZE_BUFFER_RATE）
      "margin_warning_rate": 0.0,            // 毛利告警阈值（对齐 POINTS_POLICY_MARGIN_WARNING_RATE）
      "negative_margin_block_enabled": true, // 负毛利阻断（对齐 POINTS_POLICY_NEGATIVE_MARGIN_BLOCK_ENABLED）
      "settlement_formula_version": "<版本>" // 结算公式版本
    }
  },

  // === 编辑基线投影（materialized：hash + 投影正文，恢复可重放） ===
  "revision_set_hash": "<三类 head 确定性投影的规范化 hash, §2.9>",
  "revision_heads": {
    "dialogue": "<head revision_hash> | null",
    "director_override": "<head revision_hash> | null",
    "voice_binding": "<head revision_hash> | null"
  },
  "revision_projection": {
    "dialogue": {...} | null,          // head revision payload 正文
    "director_override": {...} | null,
    "voice_binding": {...} | null
  },

  // === 输入签名（R8：版本化 signed_payload，hash 域显式白名单；R9：派生事实不参与） ===
  // signed_payload = {"signed_payload_version": 1, "engine_config_payload": ..., "script_facts": ...|null,
  //   "source_chapter_content": ...|null, "voice_resolution": ...|null, "run_options": ...,
  //   "billing_context": {...计价事实...}, "revision_set_hash": ..., "revision_projection": ...}
  // 参与 hash：全部业务输入正文与计价事实字段（含 billing_snapshot 内全部计价事实，signed_payload_version 本身参与）；
  // 排除：input_signature 自身与纯审计字段（captured_at / snapshot_id / billing_rules_version）——
  // 相同业务输入 + 相同计价事实 → 相同签名（重试/幂等成立），审计字段变化不影响签名；
  // 派生事实（R9，R10 分阶段）：full/script_only 运行中生成的剧本/音色/拓扑不参与输入签名（创建时未知），
  // 由 checkpoint 各子项 hash（generated_script_facts_hash / voice_resolution_hash / scene_topology_hash）单独校验（§2.11）。
  "input_signature": "sha256(canonical_json(signed_payload))"
}
```

**计费快照捕获顺序与作用域（R8 修正，解决"预检需要 run 快照、run 快照又由预检捕获"的顺序循环；R9 补全冻结-派发闭环）：**

- **六步顺序**（`routes_projects.py` 等入口统一改造；现状为"实时价格预检 → 创建/入队 → 之后冻结"，见 `routes_projects.py` 约 241/271 行；`task_support.py` 约 779 行 `apply_async` 直接派发、约 118 行冻结异常被吞、`repository.py` 约 948/990 行自带 `db.commit()`，均须改造）：
  1. **捕获不可变 pricing snapshot**（入队前）：`resolve_audiobook_billing_pricing_context` 改造为"捕获动作"——一次性读取当前定价策略与 provider 目录价，构造不可变 `billing_snapshot`（字段见上）；**每 run 独立捕获**（同一批次多次运行各有自己的计价事实）。
  2. **准入预检**：以该 snapshot 的计价事实 + **实时账户余额**执行预检（`build_audiobook_task_points_precheck` 消费 snapshot，不再读实时定价策略）——**预检为乐观准入（无锁聚合读数），不构成资金裁决**：余额与冻结的最终裁决在冻结事务内账户级锁下重新聚合（第 3 步，R11/P0-2），预检仅用于提前拦截明显不足的请求。
  3. **同一事务完成"账户锁 + 重聚合 + 建 run + 快照 + 指针 + 冻结"**（R9 扩展，§1.4 同事务保证；R10 事务所有权声明，P0-3；R11 账户级资金不变量，P0-2）：**事务开头先取 `pg_advisory_xact_lock(user_id)`**（积分账户无独立行可 FOR UPDATE——冻结事实是 AdminOperationLog 事件流，advisory 锁为最合适载体；锁序见 §2.9，账户锁置顶；**锁键收敛前提，R12/P0-3**：账户级不变量只在"所有改变同一用户余额或冻结额的路径都使用同一 advisory 锁键"时成立——通用冻结入口 `record_points_billing_freeze`（`user_center_points_events.py` 约 372 行）现状无锁，拆书（`book_parser.py` 约 254 行）、小说协同扩展（`workflow/routes_expand.py` 约 649 行）、短剧独立冻结路径（`dreamweaver_tasks_pkg/_task.py` 约 414 行）与管理员积分调整（`admin/users.py` 约 396 行）都是独立写路径；必须将"用户积分账面变动 + 余额/冻结校验"收敛到**共享 points mutation service**（见下与 §2.9），任何冻结/结算/释放/管理员调账及影响可用余额的业务事件都经该 service 并在同一锁键下执行；收敛完成前不得宣称维持用户账户级资金不变量）→ **锁内重新聚合账户余额 + 全部有效冻结**（含本批次全部 run 的冻结）→ 统一裁决本批次冻结总额是否可行（第 2 步预检仅乐观准入，本裁决才是资金不变量最终裁决点）→ 创建/锁定唯一 active `ChapterAudio`（首次运行在事务内创建，R9/P0-3；唯一性由 §1.1 部分唯一索引保护，R10/P0-4）→ 创建 `ChapterAudioRun`（含 `chapter_audio_id`/`run_input_snapshot`/**预生成固定 `celery_task_id`（唯一索引，派发意图与消息一一对应，R11/P0-1）**/**`predecessor_run_id`（上一 desired run id，条件补偿前提，R11/P1-4）**/**`dispatch_attempts=0`/`next_dispatch_at=now()`（R11/P0-1）**/`dispatch_status='pending'`，更新 `desired_run_id`）→ **同一事务内执行积分冻结**（run 级 key `audiobook:{audiobook_project_id}:run:{run_id}`；`_safe_record_audiobook_billing_freeze` 不再吞异常：失败向上抛使事务整体回滚，run/指针/快照/冻结一并消失，不产生"未冻结先执行"；**冻结账户（冻结事务的 `target_user_id`）同步写入 `ChapterAudioRun.billing_account_user_id` 与 `run_input_snapshot.billing_context.billing_account_user_id`（不可变，R17/P1-3——计费账户唯一权威来源，运行期不随 `Project.user_id` 变化）**；**本批次全部 run 的冻结在同一账户锁下一次性裁决并写入，锁内裁决一次——杜绝"两请求分别通过预检、冻结总额超余额"（R11/P0-2）**）。**R10 事务所有权（P0-3）**：整个入队调用图内的 `repository`（`create_task` 约 1172 行、`attach_celery_id` 约 1183 行、`create_run`/`create_runs` 约 948/990 行的内部 `db.commit()`）、checkpoint 构造（`task_support.py` `enqueue_chapter_runs` 约 694 行的 `db.commit()`）与计费 helper（`_create_points_billing_event_log` 约 305 行、`_safe_record_audiobook_billing_freeze`）**全部只允许 `add`/`flush`，不允许 `commit`**——事务所有权唯一归最外层应用服务（`routes_*` 入口），任何内部 `commit()` 都会把同事务中尚未完成的 run/指针/快照/冻结提前提交，后续失败无法整体回滚（冻结后任一步异常都必须不留任何残留，见 §7 测试）。
  4. **派发：run 即 outbox，dispatcher 租约认领重放**（R9 新增，冻结成功才能投递；R10 派发单位重构，P0-2；R11 升级可靠派发闭环，P0-1）：**每个 run 一条独立 Celery 消息 + 独立 `celery_task_id`**（不再把整个 `chapter_ids` 塞进同一个 signature 共用一个 task id，现状 `task_support.py` 约 727/760/779 行；`task_record` 与 run 一对多）。**任务-派发数据合同（R11/P0-3，R12 单一事实源收紧，P1-1）**：父 `AudiobookTask` 保持唯一 `celery_task_id` 列作为父任务占位，每 run 一条 `audiobook_task_dispatches` 子派发记录（§5 阶段 1.1）——**单一事实源为 `ChapterAudioRun` 自身（run 即 outbox）**：派发状态（`dispatch_status`/`dispatch_attempts`/`next_dispatch_at`/`dispatch_claim_token`/`dispatch_claimed_at`）、执行租约（`claim_token`/`claimed_at`/`lease_expires_at`）、进度（`progress`）与暂停（`status='paused'`）均以 run 列为准；**子表降级为"父子关系 + 可重建展示投影"**：仅保存 `task_id`/`run_id`/`chapter_audio_id`/`created_at`（**不含 `celery_task_id`，R14/P1-a 统一单一事实源**），**不复制 status/claim/lease/attempts/progress/last_error**（消除双写不一致源），展示所需字段（含 `celery_task_id`）经 JOIN `ChapterAudioRun` 获得——**`ChapterAudioRun.celery_task_id` 是唯一事实**，查询/暂停/恢复/SSE 一律 JOIN run 取用（删除一切 `dispatch.celery_task_id = run.celery_task_id` 一致性描述，数据库层不再需要也不允许两处值），并施加**复合外键 `(run_id, chapter_audio_id) → chapter_audio_runs(id, chapter_audio_id)`**（保证子派发的 `chapter_audio_id` 必须属于该 run，R12/P1-1）。**父任务聚合输入为 run 状态**，终态矩阵**互斥且有优先级**——**唯一事实源为 §1.1 父任务互斥矩阵（R17/P1-2 计数穷尽规则，优先级：①任一 `unknown` fail-closed → ②任一进行中 → ③全部 `succeeded` → ④全部 `cancelled` → ⑤至少一 `succeeded` 且存在失败/取消 → ⑥无 `succeeded` 且至少一 `failed`），此处不复制枚举（R16/P1-2**：本段旧矩阵“①cancelled → ②failed → ③进行中 → ④succeeded、无 unknown 分支”与正式规则矛盾——`{unknown, running}`/`{unknown, failed}` 会落入错误分支破坏 fail-closed 语义；R17/P1-2 再修：旧优先级③④为“任一 cancelled/failed 且其余全部终态”的谓词组合，{cancelled, failed} 前置成立但无结果——正式矩阵已改为基于计数的穷尽规则；任何聚合实现一律以 §1.1 `normalize_run_status` + 互斥矩阵为准，禁止在六步流程/API 章节/验收/测试中另行复制枚举）。进度 = Σ run.progress 加权（按 run 数）。**job_id 语义（R13/P1-a）**：多章节请求返回的 `job_id` = **命名空间字符串 ID `task:{AudiobookTask.id}`**——替换 raw 数值父 ID，消除与 Celery UUID 的歧义（`task:123` 明确为父任务 ID，不与任意 Celery UUID 混淆）。以下所有 API 合同同步更新：**响应 schema** `AudiobookTaskStatus` 新增 `task_id`/`children` 字段（保留 `celery_task_id` 兼容期）；**列表接口**返回父任务聚合视图含 children 摘要；**暂停/恢复/取消**端点定位子派发（`celery_task_id` 查询兼容保留）；**SSE topic** 从 URL 中的旧 task ID 改为按 `job_id` = `task:{id}` 订阅（`routes_misc.py` 约 22 行 `/tasks/{task_id}/stream` 保留旧 UUID 路径兼容）；**前端类型** `StageStatus` 同步 `cancelled`/`completed_with_partial_failure`（R13/P0-a），`coerceStageStatus` 降级修复，`extractQueuedAudiobookJobId` 接受字符串 `task:{id}`；**本地任务缓存归一化**从优先 `celery_task_id` 改为优先 `job_id`（`utils.ts` 约 162 行 `rawTaskId` 选择器）。旧 Celery UUID 查询兼容期至少保留 1 个发布周期。`GET /tasks/{task_id}/status` 优先按父任务 ID 解析返回聚合视图（含 children 摘要：各 run 状态/进度/错误），命中子派发 celery_task_id 时返回单 run 视图，单 run 时退化为原语义（现有单 job_id 客户端 API 兼容）；SSE 事件携带 `run_id` + 父 `job_id`，前端按 job_id 聚合。暂停/恢复/取消按 run 级操作（子状态含 `pause_requested` 过渡态，§5 阶段 1.1），父任务聚合下发。**run 行自身即派发意图记录（简化 outbox，R11/P0-1）**：第 3 步事务内已持久化 `dispatch_status='pending'` + 预生成固定 `celery_task_id` + `dispatch_attempts=0`/`next_dispatch_at=now()`——事务提交后即使进程在首次 `apply_async` 前崩溃，run 行仍带完整派发意图，由独立 dispatcher 重放，**不再依赖"事务提交后立即同步 apply_async"这一易碎窗口**。派发协议：
     - **dispatcher 租约认领（R11/P0-1，R12 补未认领重投，P1-5）**：独立 dispatcher（beat 定时任务，挂载 `celery_app.py` 既有 `beat_schedule`）CAS 认领：`UPDATE chapter_audio_runs SET dispatch_attempts = dispatch_attempts + 1, next_dispatch_at = now() + :retry_backoff, dispatch_claim_token = :token, dispatch_claimed_at = now() WHERE id = :run_id AND dispatch_status = 'pending' AND next_dispatch_at <= now() AND (dispatch_claim_token IS NULL OR dispatch_claimed_at < now() - :claim_expiry)`；rowcount=1 才 `apply_async`（携带 run 持久化的固定 `celery_task_id`），成功 → 结果回写带 token CAS（R14/P1-d）：`UPDATE chapter_audio_runs SET dispatch_status='dispatched', dispatched_at=now(), dispatch_claim_token=NULL, dispatch_claimed_at=NULL WHERE id = :run_id AND dispatch_status = 'pending' AND dispatch_claim_token = :token`（写 `dispatched_at=now()`（新列，R12/P1-5）并清 claim token；**rowcount=0 → run 已被其他 dispatcher 接管（claim 过期后 B 认领），静默退出，不清除 B 的新 claim**）；失败按三态处理（见下）；**dispatched 未认领重投（R12/P1-5）**：消息成功投递后、worker 尚未 CAS 认领前，run 处于 `dispatch_status='dispatched'` 且无 worker lease（`claim_token IS NULL`）——若消息在 broker 侧丢失/过期/被清理（`visibility_timeout` 到期但 worker 从未认领），`pending` 扫描器永远不会再处理它；补独立 CAS：`WHERE id = :run_id AND dispatch_status = 'dispatched' AND dispatched_at IS NOT NULL AND dispatched_at + :first_claim_deadline < now() AND claim_token IS NULL`（`first_claim_deadline` 建议 10 分钟，须小于 `visibility_timeout`）→ 视为未投递重投：**复用固定 `celery_task_id` 重新 `apply_async`** 并重置 `dispatched_at`（`dispatch_attempts` 计数与超上限转 unknown 同 pending 路径）；worker lease 保证即使 broker 实际仍存旧消息，重投也不会产生重复外部调用（认领 CAS 同一时刻仅一个 worker 持有执行权）；
     - **stale-pending 扫描器（R11/P0-1，最低要求，非可选项）**：beat 定时扫描 `dispatch_status='pending'` 且 `next_dispatch_at <= now()` 且 claim 已过期的 run 重放——覆盖"事务提交后、首次派发前进程退出"的悬挂窗口；**`dispatch_attempts` 超过上限（如 5 次）转 `dispatch_status='unknown'` 走人工对账**，不再无限重试；
     - **`apply_async` 结果按三态处理**（`dispatch_status` 落库，值域 `pending`/`dispatched`/`cancelled`/`unknown`，§1.1 迁移清单；**三态回写全部带认领 token fencing（R14/P1-d）**：任何结果回写必须先经 `WHERE dispatch_claim_token = :token` CAS（见各态）——避免"认领过期 → 其他 dispatcher 接管 → 旧调用迟到返回"竞态破坏新 claim 或误补偿已投递任务）：
       - **明确失败**（broker 连接拒绝/消息格式被拒等可判定"未投递"的异常）→ **先过结果回写 token CAS（R14/P1-d）**：`UPDATE chapter_audio_runs SET dispatch_status='cancelled', dispatch_claim_token=NULL, dispatch_claimed_at=NULL WHERE id = :run_id AND dispatch_status = 'pending' AND dispatch_claim_token = :token`——**rowcount=0（token 不匹配/已非 pending，run 已被其他 dispatcher 接管）→ 静默退出，不做任何补偿**；CAS 成功才进入补偿：**锁定 `ChapterAudio` 行 + 条件更新** `UPDATE chapter_audios SET desired_run_id = :predecessor_run_id WHERE id = :chapter_audio_id AND desired_run_id = :failed_run_id`（**rowcount=0 说明 desired 已被更新 run 接管，只取消并释放失败 run、不覆盖新指针，R11/P1-4**）→ 释放该 run 已冻结积分（幂等键防重复释放）、run 置 `cancelled`——**指针补偿、取消、冻结释放全部仅在 token CAS 成功后执行，且与 CAS 处于同一事务**（任何一步不允许脱离 token CAS 单独执行）——不留下"已冻结未派发"的悬空任务；
       - **结果未知**（网络超时/响应丢失等无法判定 broker 是否已接收）→ **禁止把 unknown 当作"确定未投递"**：run 保持 `pending`、**先过结果回写 token CAS（R14/P1-d）**：`UPDATE chapter_audio_runs SET dispatch_status='unknown', dispatch_claim_token=NULL, dispatch_claimed_at=NULL WHERE id = :run_id AND dispatch_status = 'pending' AND dispatch_claim_token = :token`（rowcount=0 → 已被接管，静默退出），CAS 成功后 `dispatch_status='unknown'`、**不释放冻结、不置 cancelled**——broker 可能已接收并最终执行；此语义下补偿会释放已退款任务的冻结，而 worker 仍可能执行并产生供应商费用（现状活动检查仅拒绝 cancelled run，见 `background_jobs_shared.py` 约 122 行，且 full/`audio_from_scripts` 在供应商调用前没有原子认领检查，见 `background_jobs_full.py` 约 253 行、`background_jobs_audio.py` 约 311 行）。unknown 进入对账流程（§1.4：查询 broker/任务状态，确认已执行则补记 `dispatched` 并保留 run，确认未执行才走补偿；长期未知由人工处理）；
       - **明确成功** → 同样先过结果回写 token CAS（R14/P1-d）：`UPDATE chapter_audio_runs SET dispatch_status='dispatched', dispatched_at=now(), dispatch_claim_token=NULL, dispatch_claimed_at=NULL WHERE id = :run_id AND dispatch_status = 'pending' AND dispatch_claim_token = :token`（rowcount=0 → 已被接管，静默退出，**不得清除接管者的新 claim**）。
     - **outbox 定位（R11/P0-1 修订 R10 表述）**：R10 曾把"消息表与业务同事务写入、独立投递器重放"列为可选增强——**本版起不再可选**：run 行派发意图字段（`dispatch_status`/`celery_task_id`/`dispatch_attempts`/`next_dispatch_at`/claim 字段）与业务同事务落库 + 独立 dispatcher 认领重放，即**最低要求的 outbox**；独立 message 表实体（多消费者/按序投递）仍可不做，但"派发意图持久化 + 独立重放器"必须实现。
  5. **批量章节策略**（R9 新增，R10 按 run 独立派发，R11 锁内批量裁决）：多章节请求中任一章节**冻结失败** → 整个事务回滚（不部分成功）；**本批次全部 run 的冻结在同一账户锁下一次性裁决并写入**（R11/P0-2：锁内重聚合余额 + 全部有效冻结 + 本批次全部冻结统一判定，不允许逐 run 分开裁决）；全部冻结成功才进入派发阶段；派发阶段**逐 run 独立处理**（每 run 独立消息天然支持"第 1 章已投递、第 2 章投递失败"），失败/未知的 run 按第 4 步语义各自补偿或对账，已成功派发的 run 不受影响（避免重复派发）。
  6. **结算：统一 finalizer 计费封口（R17/P0，替代“最后一条 ledger 收敛时顺手 settle”）**：使用该 run 快照内嵌的 snapshot + `billing_usage_ledger` 实际用量（§8.5，R9/P1-3；R10 升级为调用前 pending → 成功转 succeeded 状态机，P1-3；**R11 扩展为四态 pending/succeeded/confirmed_failed/manual_reconciliation，P1-2**：succeeded 才结算，confirmed_failed 不结算，manual_reconciliation 人工对账转态后再结算，§1.1/§8.5）。**最终结算只能由统一 finalizer 执行**——前置条件：run 已进入不可继续调用供应商的执行终态（`completed`/`failed`/`cancelled`/`expired`）且无有效 worker lease（`lease_expires_at IS NULL` 或 `< now()`）、该 run 全部 ledger 已终态（无 `pending`/未收敛 `manual_reconciliation`）；finalizer 单事务顺序：`pg_advisory_xact_lock(billing_account_user_id)`（账户锁，来源见 R17/P1-3）→ `SELECT ... FROM chapter_audio_runs WHERE id = :run_id FOR UPDATE` → 校验上述前置条件 + `billing_finalized_at IS NULL` → 置 `billing_finalized_at = now()` → strict barrier → 执行唯一最终 settle → **单次 commit**；任何路径（worker 完成/失败落库、人工收敛、dispatcher 补偿）都不得绕过 finalizer 直接 settle——**run 未终态时人工收敛只提交 ledger 与审计、不立即 settle，等 run 真正结束后由 finalizer 结算（R17/P0：strict barrier 只检查已有 ledger 无法阻止 worker 结算后新建 pending ledger——账户锁不覆盖 worker 的 ledger 写入路径，settle 在先、ledger 在后会产生无法补扣的永久少扣费，因为禁止 supplement 且唯一索引阻止二次 settle）**。**finalizer 触发协议（R18/P0，修复 R17 主路径缺口）**：R17 只定义了 finalizer 前置条件、未定义触发路径——worker 写 completed 时通常还握着有效租约（“无有效 lease”前置永不满足）、租约过期后无扫描器重试、全部 ledger 已 succeeded 时人工收敛入口进不去，成功跑完的 run 冻结会永久挂死。三条触发路径：①**worker 终态主路径**——worker 终态事务按全局统一锁序执行（**R19/P0：先取账户 advisory 锁再取 run 行锁**，取锁后重新校验，见下方执行终态写协议）：账户锁内锁 run → 写执行终态的同一条 CAS 清租约（`claim_token=NULL, claimed_at=NULL, lease_expires_at=NULL`）→ 按证据关账 → 同事务执行 finalizer 逻辑（此时“终态 + 无有效租约”前置天然满足，正常成功当场结算并释放冻结）；②**人工收敛联动**——收敛后 run 已终态 + 无租约 + barrier 通过则同事务封口结算（既有语义）；③**beat 扫描器兜底**——`billing_finalizer_scan`（beat 定时任务）周期性重试“执行终态 ∧ `billing_finalized_at IS NULL` ∧ 无有效租约”的 run（run 行本身即结算意图记录，与“run 即 outbox”哲学一致，不引入新结算意图表——R18/P0 替代 R17 记录规则“如需拆分事务必须另建结算意图/outbox + 扫描器，本版不选，KISS”立场：无扫描器时终态 CAS 崩溃或 finalizer 失败会让冻结永久挂死，beat + run 行状态是最低兜底）。**取消/失败按证据关账（R18/P0）**：写 run `cancelled`/`failed` 必须同事务按证据关账本 run 全部 pending ledger（见下方执行终态写协议），否则 barrier 永远过不了、冻结挂死。
- **worker 消费租约协议（R10，P0-1；R11 升级为可恢复租约，P1-1；R12 拆分首认领与过期接管，P0-1；R17/P0 计费封口前置）**：任何 worker 在**供应商调用之前**必须完成**租约认领**——同一事务内 CAS 更新，**两条明确的状态迁移**：**首认领**（run 尚未被任何 worker 认领）：`UPDATE chapter_audio_runs SET status='running', dispatch_status='dispatched', claim_token=:token, claimed_at=now(), lease_expires_at=now() + :lease_interval WHERE id = :run_id AND status IN ('pending','queued') AND dispatch_status IN ('pending','dispatched','unknown') AND (claim_token IS NULL OR lease_expires_at < now()) AND billing_finalized_at IS NULL`；**过期接管**（run 已被认领但租约过期，原 worker 崩溃）：`UPDATE chapter_audio_runs SET claim_token=:token, claimed_at=now(), lease_expires_at=now() + :lease_interval WHERE id = :run_id AND status = 'running' AND dispatch_status IN ('dispatched','unknown') AND lease_expires_at < now() AND billing_finalized_at IS NULL`——**接管只换执行权、不回退运行态**（status 保持 `running`；R11 原文仅接受 `status IN ('pending','queued')` 的 CAS，导致"认领成功 → worker 崩溃 → 租约过期 → 消息重投"后新 worker 永远无法命中 CAS、run 永久卡死 `running`，与验收 57 目标矛盾，R12/P0-1 修复）；**计费封口前置（R17/P0；R18/P1-2 建账合同修正）**：两分支 CAS 均带 `billing_finalized_at IS NULL`——已计费封口的 run 禁止任何 worker 认领与继续调用供应商；**建账合同（R18/P1-2 替代 R17“与首次认领 CAS 同一事务”）**：一个 run 会有多次 TTS/ASR/remix 供应商调用，若建账与首次认领绑死，要么整段执行握长事务（不可接受）、要么提交 pending 时丢失 run 锁（“settle 在先、ledger 在后”会回来）——改为**每次调用独立建账短事务**，锁**当前租约**（非首次认领事务）：`SELECT id FROM chapter_audio_runs WHERE id = :run_id AND status = 'running' AND claim_token = :token AND billing_finalized_at IS NULL FOR UPDATE`（rowcount=0 → 终止，不建账、不调用供应商——**谓词同时校验执行状态、当前租约 token 与封口字段，不得只查封口字段**）→ 插入 `status='pending'` ledger（`commit_stage='pre_call'`）→ commit（pending 在调用前提交，崩溃窗口可见）；finalizer 与 worker 双方仍以 run 行锁串行化：finalizer 先置 `billing_finalized_at` 提交 → worker 建账事务行锁谓词不命中终止、无新 ledger；worker 建账事务先提交 → finalizer 的 barrier 看到 pending 拒绝结算——**不可能出现“settle 在先、ledger 在后”**（账户锁不覆盖 worker 的 ledger 写入路径，run 行锁才是封口与新增用量的共同串行化点；heartbeat 续期不检查 finalized——仅认领/新建 ledger 时检查，已封口 run 的旧 worker 心跳自然过期）；两分支 CAS 均同步更新 `claim_token`/`claimed_at`/`lease_expires_at` 三字段；展示一致性由服务层聚合 JOIN `ChapterAudioRun` 保证（子派发表不自存投影字段，R13/P1-d）；rowcount==0（run 已被取消/不存在/**租约未过期仍被他 worker 持有**/**已计费封口**）→ **不调用任何供应商，立即终止**。**租约续期（heartbeat）**：供应商调用期间周期 `UPDATE ... SET lease_expires_at = now() + :lease_interval WHERE id = :run_id AND claim_token = :token`——claim_token 不匹配（租约已被接管）立即终止执行。**心跳与阻塞调用解耦（R13/P1-e 收紧 R12/P0-1"二选一"）**：heartbeat 数据库续期失败时旧 worker 的 HTTP 请求可能仍在供应商侧执行，token fencing 只能阻止旧 worker 后续落库或新发起调用，不能撤回已发送的请求。约束收紧：**对非幂等 provider（不接受外部幂等键、无可查询请求 ID），强制单次供应商请求最长超时 < `lease_interval`**（如 `lease_interval=15` 分钟则单次请求超时上限 ≤ 10 分钟）——**不允许仅用独立 heartbeat 而不约束请求超时**；对**可查询/幂等 provider**，heartbeat 必须独立于阻塞的供应商调用执行（独立线程/单独调度周期续期，不允许 heartbeat 与供应商调用串行共享同一阻塞路径），且接管者必须先按持久化证据恢复查询（`billing_usage_ledger` 证据字段），只有证实可幂等重放时才允许再次调用供应商，否则转 `manual_reconciliation`。测试覆盖"旧请求持续超过 lease、heartbeat 已失效、新 worker 接管"的并发窗口——断言新 worker 按证据恢复查询（非重复调用供应商），且旧请求返回后落库操作被 token fencing 拒绝（claim_token 不匹配）。**过期租约接管**：worker CAS 后崩溃（未续期未完成），`lease_expires_at` 到期后任何 worker 均可按"过期接管"分支接管（dispatcher 也可对 `dispatch_status='dispatched'` 但租约过期的 run 重新投递）；接管分支前置校验 run 未被取消（cancelled 的 run 禁止接管）。**ACK 时点 = 任务完成/失败落库后**（先落库后 ACK）。**worker lost 行为（R11/P1-1）**：`celery_app.py` 约 39 行配置补 `task_acks_late=True`、`task_reject_on_worker_lost=True`、`visibility_timeout` 对齐 `lease_interval`（现状无任何 ACK/visibility 配置，约 87-89 行 Windows 强制 solo 池 + concurrency=1 下消息不自动重投）——worker 进程异常退出 → 消息重投 → 新 worker 接管过期租约。**与 provider recovery/ledger 衔接**：供应商调用点仍以 `provider_recovery.py` 的恢复方法（request_query/temporary_url）与 `billing_usage_ledger` 状态机为准（§1.1），租约只决定"哪个 worker 有权继续执行"，不替代供应商结果查询。**dispatch 状态与租约状态解耦**：`dispatch_status` 表示"消息投递与投递结果"，租约字段（`claim_token`/`claimed_at`/`lease_expires_at`）表示"当前执行权归谁"。现状 `is_chapter_generation_target_active`（`background_jobs_shared.py` 约 72 行）的 cancelled/expired 检查保留并前移为认领的前置条件，但 full/`audio_from_scripts`/`script_only` 在供应商调用点（`background_jobs_full.py` 约 253 行 `generate_chapter_audio`、`background_jobs_audio.py` 约 311 行 `generate_chapter_audio_from_script`）之前**必须**经过认领（现状仅有生成后的复核检查，约 274/307/332 行，不满足"调用前"）；认领成功即确认 broker 确已投递（unknown 对账的关闭条件）；认领后取消的窗口由生成循环内既有复核点（约 274/307/346/376/425/450 行）终止。**执行终态写协议（R18/P0；R19/P0 统一锁序——终态事务先取账户锁，消除“run 行锁 → 账户锁”死锁环）**：worker 终态事务必须严格遵循与 finalizer/人工收敛完全相同的全局锁序“账户 advisory 锁 → run 行锁 → ledger 行锁（多条按 id 升序，§2.9 三层锁序 + 锁内写入顺序合同，R20/P1-1，R21/P2-1）”（§2.9/§8.5）。R18 原文“终态 CAS（先锁 run 行）→ 同事务调 finalizer（后取账户锁）”与人工收敛等“账户锁 → run 行锁”路径构成经典死锁环（事务 A 持 run 行锁等账户锁、事务 B 持账户锁等同一 run 行锁），R19/P0 修复。事务内固定顺序：①**事务开头取账户锁** `pg_advisory_xact_lock(billing_account_user_id)`（`billing_account_user_id` 为不可变列（R17/P1-3），可在锁前以普通 SELECT 读取，运行期不变，锁前读取安全）→ ②`SELECT ... FROM chapter_audio_runs WHERE id = :run_id FOR UPDATE` → ③**取锁后重新校验**——`status = 'running' AND claim_token = :token AND billing_finalized_at IS NULL`（**禁止使用锁前读取的任何结果**：取锁前该 run 可能已被过期接管（token 变更）、取消或计费封口；任一不满足 → 回滚终止，按幂等已处理对待）→ ④写执行终态（`completed`/`failed`/`cancelled`）+ 同一条 CAS 清租约——`UPDATE chapter_audio_runs SET status = :terminal_status, result_render_status = :result, claim_token = NULL, claimed_at = NULL, lease_expires_at = NULL WHERE id = :run_id AND status = 'running' AND claim_token = :token`（**R17 缺口：终态不清租约则 finalizer 的“无有效 lease”前置永不满足，成功跑完的 run 冻结永久挂死**）→ ⑤同事务按证据关账本 run 全部 `status='pending'` ledger（**涉及多条 ledger 时统一按 `ledger.id` 升序加锁更新（统一三层锁序第③层，R20/P1-1）**）：`commit_stage = 'pre_call' AND provider_request_id IS NULL AND idempotency_key_sent = false`（无供应商证据）→ `confirmed_failed`（未产生用量，不结算）；`commit_stage IN ('post_call','result_persisted')` 或 `provider_request_id IS NOT NULL` 或 `idempotency_key_sent = true`（已发出或结果不明）→ `manual_reconciliation`（结算前人工对账，零二次调用）——**取消/失败不得残留 pending，否则 barrier 永远过不了、冻结挂死**→ ⑥关账完成 → **同事务执行 finalizer 逻辑**（账户锁与 run 行锁均已在本事务按正确锁序持有，与 §8.5 finalizer 单事务顺序完全一致，不重新申请锁；此时“终态 + 无租约”前置天然满足：barrier 通过 → 封口 + settle、冻结释放；存在 `manual_reconciliation` → 保留冻结等人工对账）→ ⑦单次 commit。**beat 扫描器兜底**：终态 CAS 崩溃或 finalizer 执行失败 → `billing_finalizer_scan` 扫描 `status ∈ 终态 ∧ billing_finalized_at IS NULL ∧ (claim_token IS NULL OR lease_expires_at < now())` 重试（run 行即结算意图记录，不引入新表，见六步第 6 步 R18/P0）；租约未清且未过期时 finalizer 前置拒绝（防止 settle 与在途调用竞速），自然过期后重试。
- **计费作用域（R8 决策：run 级；R9 统一命名，P2-4；R10 版本头 key 统一，P2-2）**：`build_audiobook_billing_key` 改为 `audiobook:{audiobook_project_id}:run:{run_id}`（现状 `user_center_points_events.py` 约 64 行参数名即 `audiobook_project_id`，返回批次级 `audiobook:{id}`；文档不再使用含义不清的 `{project_id}`）——同一批次多次重渲染时各 run 独立冻结/结算/幂等；**批次级账单为展示层聚合**（按 audiobook_project 汇总各 run 计费事件），冻结/结算/幂等层不使用批次级 key；源小说 `project_id` 仅用于展示聚合；历史批次级冻结记录保持兼容（仅展示聚合）。

- **创建阶段与执行阶段分离（R7 修正，R9 补齐音色时序）**：新运行创建时按上述 run_type 合同计算并冻结 `run_input_snapshot`——`audio_from_scripts`/场景重渲染在**创建运行的同一事务中**读取当前已审批 `script_json`、revision heads 投影并解析音色后立即内嵌（读一次即冻结）；`script_only`/`full` 冻结原章输入（章节 `content`），`script_facts`/`voice_resolution` 为 null（**运行中派生：剧本生成后冻结 `derived_execution_facts`，§2.11/R9**）。**运行执行与恢复阶段禁止重新读取** `Project.audio_config`/`ChapterAudio.script_json` 构造输入；恢复任务只消费本快照 + checkpoint 派生事实（含不读 `engine_config_snapshot`——正文已内嵌）。
- `ChapterAudioRun` 增加 `run_input_snapshot`（Text）、`revision_set_hash`（String(64)）列：`revision_set_hash` 用于区分同一章节同一 `run_type` 的不同编辑运行（查"某次编辑后是否已重渲染"）；`input_signature`（String(64)）为运行输入规范化签名，幂等重试与审计共用。
- **历史运行处理**：`run_input_snapshot` 列为 nullable。迁移后历史运行无该字段时的行为：
  1. 由 `checkpoint_json`（`_build_generation_checkpoint_payload`）可验证**恢复出全部正文**的可验证历史运行 → 脚本化回填 `run_input_snapshot`（含 `reconstructed: true` 标记），并允许恢复。回填同样按 run_type 合同判定内容完整性：`full`/`script_only` 允许 `script_facts` 缺失（恢复依赖 checkpoint），`audio_from_scripts` 必须有 `script_facts` 正文。
  2. 不可回填正文（checkpoint 不含完整 payload，仅有部分 hash）的历史运行 → `run_input_snapshot = null`，仅允许展示与审计，**禁止恢复**（恢复入口返回"历史运行输入不可用，请重新生成"）。

**批次复用规则（防跨引擎污染）：**

- 仅当**`engine_mode` 一致且 `engine_config_fingerprint` 一致**（规范化 hash 比较，审计元数据不参与）时才允许复用既有 `AudiobookProject`；任一不一致必须新建批次。
- 两阶段流程（`script_only` → 后续 `audio_from_scripts`）：
  - 未切换引擎时沿用原批次（`engine_config_fingerprint` 一致自然命中复用条件）。
  - 用户切换引擎后，第二阶段自动落到新引擎的新批次。新批次需要明确剧本来源方案：**将已审批剧本复制为新批次的不可变 `ChapterAudio.script_json` 快照**，并记录 `source_audiobook_project_id` 与 `source_chapter_audio_id` 供审计回溯。不做"只读引用"（旧批次软删除后引用悬空）、不自动重新 `script_only`（用户已审批过的剧本不应无端重跑审核流程）。
  - **复制合同（完整化）**：复制内容至少包含 `script_json` 正文、`script_status = 'approved'`（`audio_from_scripts` 前置校验明确检查目标批次 `script_status == 'approved'`，见 `routes_projects.py` 约 338 行——只复制 JSON 不足以通过现有校验）、源 `script_json` 的规范化 hash 与审核证据（`script_review_json`）及审核版本。复制后的新批次 `script_status = 'approved'` 且自带审核证据快照，无需重新审核。**持久化落点（§1.1 迁移清单）**：新批次 `ChapterAudio` 除 `source_audiobook_project_id`/`source_chapter_audio_id` 外，另存 `source_script_hash`（String(64)，源 script_json 规范化 hash）、`source_script_review_version`（String(64)，可空）与 `source_provenance_json`（JSON：复制时间、源 `script_review_json` 快照、审核版本、复制操作者等审计 payload）——复制合同要求与持久化字段一一对应，不允许"合同有要求、表无落点"。
  - **运行期互不依赖**：两阶段产物运行期互不引用——新批次生成/恢复/计费不读取源批次任何数据；来源引用仅保留为**可空审计字段**（`ChapterAudio.source_audiobook_project_id`/`source_chapter_audio_id`，见 §1.1 迁移清单），源批次软删除不影响新批次运行。
- 恢复/续跑永远落在原批次（§2.11），不触发复用判定。

**`AudiobookProject.voice_mapping` 废弃：**

- 现状：`background_jobs_scripts.py`（约 493-508 行）在生成完成后把 `engine.voice_manager.export_to_db()` 写回 `audiobook_project.voice_mapping`，与"快照不可变"直接冲突。
- 决策：`voice_mapping` 列**废弃写入**（保留列与存量数据，只读兼容；不再有任何后台路径向其写入）。运行时自动分配的音色结果改写到 `Project.audio_config.engines.{mode}.tts_models.{model}.characters`（经统一音色持久化链路，引擎分支隔离），并作为快照捕获内容；`voice_mapping` 读取路径（`base_voice_mapping` 参数）迁移为**仅从快照解析**，存量 `voice_mapping` 数据保留仅供展示与审计，**不参与任何运行输入**（`legacy_unfrozen` 批次禁止运行，不存在"快照缺失时 voice_mapping 兜底运行"路径）。

### 2.2 audio_config 引擎分支存储（唯一读写路径）

`Project.audio_config`（JSON）顶层保留 `audio_engine_mode`（用户当前选择，可变）与 `seed_audio_model`（用户当前选择的 Seed 模型，可变；**批次创建时规范化后冻结入 `engine_config_snapshot` 业务标识字段并参与 fingerprint，见 §2.1**），角色绑定与创作偏好按引擎分支存放，**分支内部沿用既有"引擎 × TTS 模型"结构**：

```jsonc
{
  "audio_engine_mode": "seed_scene",
  "seed_audio_model": "seed-audio-1.0-multilingual",
  "engines": {
    "legacy_stems": {
      "tts_models": {
        "qwen3-tts-instruct-flash": {
          "characters": [
            {"character_id": 1, "name": "旁白", "voice_id": "Neil", "tts_model": "qwen3-tts-instruct-flash"}
          ]
        }
      },
      "audio_fx": {"enable_sound_effects": true, "enable_music": true}
    },
    "seed_scene": {
      "tts_models": {
        "seed-tts-2.0-expressive": {
          "characters": [
            {"character_id": 1, "name": "旁白", "voice_id": "zh_male_...", "tts_model": "seed-tts-2.0-expressive", "reference_source": "user_private", "reference_audio_url": "https://...", "voice_pool_publication_id": "pub_xxx"}
          ]
        }
      },
      "scene_generation_preferences": {
        "music_enabled": true,
        "music_style": "东方悬疑",
        "soundscape_intensity": "medium",
        "performance_style": "cinematic",
        "timeline_mode": "natural",
        "terminal_policy": "manual_review",
        "semantic_review_enabled": true,
        "semantic_review_mode": "shadow"
      }
    }
  }
}
```

**字符读写优先级（唯一事实规则，读与写必须一致）：**

| 层级 | 读取（`get_characters_for_model(config, engine_mode, tts_model)`） | 写入（`set_characters_for_model`） |
|------|------|------|
| 1 | `engines.{mode}.tts_models.{requested_model}.characters` | `engines.{mode}.tts_models.{model}.characters`（唯一写入目标） |
| 2 | `engines.{mode}.tts_models.{legacy_key}.characters`（沿用 `_LEGACY_MODEL_KEYS` 兼容映射） | — |
| 3 | `engines.{mode}.characters`（无 tts_models 归组的旧分支形态，只读兼容） | — |
| 4 | 旧顶层 `tts_models.{model}.characters`（**仅 mode == legacy_stems** 时回退） | 仅当 mode == legacy_stems 且模型为默认模型时镜像顶层 `characters`（向后兼容）；不再写旧顶层 `tts_models` |
| 5 | 旧顶层 `characters`（**仅 mode == legacy_stems** 时回退） | — |

- `audio_fx`：读 `engines.{mode}.audio_fx` → 回退旧顶层 `audio_fx`（仅 legacy_stems）；写 `engines.{mode}.audio_fx`，停止写旧顶层。
- `scene_generation_preferences`：仅存于 `engines.seed_scene` 分支，legacy_stems 分支不存在该键。

**历史 Seed 配置迁移映射（旧顶层 → `engines.seed_scene.scene_generation_preferences`）：**

| 旧顶层键（基线文档 §12.1） | 新位置 |
|------|------|
| `seed_timeline_mode` | `engines.seed_scene.scene_generation_preferences.timeline_mode` |
| `seed_terminal_policy` | `engines.seed_scene.scene_generation_preferences.terminal_policy` |
| `semantic_review_enabled` | `engines.seed_scene.scene_generation_preferences.semantic_review_enabled` |
| `semantic_review_mode` | `engines.seed_scene.scene_generation_preferences.semantic_review_mode` |
| `seed_audio_model` | 保留顶层（快照携带，不移动） |

- 迁移写入时机：任意一次写入动作后若发现旧顶层含上述 seed 键且 `engines.seed_scene` 分支缺失，将其映射进分支并清除旧键；读取期只读回退不就地改写。
- `resolve_engine_mode` 的 `auto` 判定必须考虑旧配置：`engines.seed_scene` 分支非空 **或** 旧顶层存在任一 seed 键 → `seed_scene`（否则历史 seed_scene 项目会被错误归一化为 legacy_stems）。
- `terminal_policy` 进入 §2.4 状态机聚合输入与快照签名（`manual_review`/`fallback`/`fail` 决定回退场景后的聚合状态）。
- `timeline_mode`/`semantic_review_*` 必须进入 Prompt 与 checkpoint 签名（基线文档既有要求，R5 将快照纳入签名链）。

**Pydantic 合约完整字段（防止字段被忽略）：**

- `CharacterAudioConfig` 补充 `reference_source`、`reference_audio_url`、`voice_pool_publication_id` 字段（当前 `projects.py` 模型缺失，运行时 `build_character_voice_mapping_item`/`validate_project_voice_references` 已消费这些键）。
- 新增 `EngineBranchConfig`（`tts_models: dict[str, EngineTtsModelConfig]`、`audio_fx`、`scene_generation_preferences`）、`ProjectAudioConfig.engines` 字段；GET/PUT/auto-voices 同步改造（阶段 1.3）。

### 2.3 seed_scene 模式下隐藏音效/配乐配置

场景生成模式下前端隐藏音效/配乐面板（`AudioFxConfigPanel`），不展示、不保存 `audio_fx`；输出格式仍保留。`legacy_stems` 模式行为不变。

### 2.4 三维章节状态投影（execution_status + published_render_status + desired_render_status）

将 R3 的五态拆为**三个正交维度**，消除"锁定/导出/进行中"语义混用（R10 命名统一：文档/接口不再使用"双维度"表述，P2-1）：

**维度一：`execution_status`（任务生命周期，已有语义延续）**

```
queued | running | paused | succeeded | failed | cancelled
```

- `execution_status` 是 API 投影值，数据库实际值（`ChapterAudioRun.status`）与投影映射如下（**投影规则与 §1.1 `normalize_run_status` 同一事实源，此处仅列 API 值域 {queued, running, paused, succeeded, failed, cancelled} 落点，禁止复制枚举，R16/P1-2**）：
  - `pending` / `queued` → `queued`
  - `running` → `running`
  - `paused` / `pause_requested` → `paused`（暂停过渡态归入暂停展示，R16/P1-2 补）
  - `completed` → `succeeded`
  - `failed` → `failed`
  - `canceled` / `cancelled` / `expired` → `cancelled`（`expired` 是合法数据库态：候选 supersede/临时片段过期清理写路径，§1.1 run CHECK；R16/P1-2 补）
- 由 `ChapterAudioRun.status`（任务生命周期）聚合，供进度 UI 与 stage graph（§2.12）渲染使用；`succeeded` 只表示"该次运行结束"，不代表章节可导出。
 **运行作用域闭合（R9，P0-3；R10 补唯一约束，P0-4）**：`ChapterAudioRun` 新增不可变 `chapter_audio_id`（外键 → `chapter_audios.id`），**首次运行（script_only/full）在入队事务内创建/锁定唯一 active `ChapterAudio`**（现状 `background_jobs_scripts.py` 约 400 行在后台剧本生成后才创建，届时已无可冻结的运行作用域——§1.4 把创建时点前移）；**"唯一 active"必须由数据库部分唯一索引保证（R10/P0-4）**——首次创建时表中无行，`SELECT FOR UPDATE` 锁不住"不存在的记录"，两个并发事务可各插入一条 active 行（现状 `repository.soft_delete_older_duplicates` 约 613 行专门清理重复 active 即反证）；`UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL`（§1.1 迁移先确定性去重再建索引），并发插入 loser 按 §2.9 SAVEPOINT 协议回滚重读，软删除恢复与该索引冲突时返回 409（§1.1）；runs 复合唯一键改为 **`(id, chapter_audio_id)`**（R8 的 `(id, audiobook_project_id, chapter_id)` 升级——`chapter_audio_id` 是比"批次+章节"更精确的作用域：同一源章节可存在于多个批次，而 run 只能属于一个 chapter_audio 实例）；`ChapterAudioOutput`/`SceneAudioArtifact` 复合外键改指 `(run_id, chapter_audio_id) → runs(id, chapter_audio_id)`，数据库层杜绝"输出/artifact 挂在另一 chapter_audio 的 run 上"；`ChapterAudio.desired_run_id`/`published_run_id` 单列外键升级为复合外键 `(desired_run_id, id) → runs(id, chapter_audio_id)` / `(published_run_id, id) → runs(id, chapter_audio_id)`（**ON DELETE RESTRICT——被 `desired_run_id`/`published_run_id` 当前引用的 run 行不可物理删除，R10/P1-1；R11/P2-2 归因修正："任何 run 只墓碑化、永不物理删除"的契约由 repository/service 层强制策略承担（清除全部 `DELETE FROM chapter_audio_runs` 入口，终态 run 仅墓碑化），双指针 FK 只保护被引用行，见 §1.1**）——指针不可能指向其他章节/其他实例的 run（§2.14/§1.1 迁移清单）。
- **多运行场景的聚合规则（双指针发布模型）**：同一章节可能存在多个 `ChapterAudioRun`（旧 completed + 新 queued + 新 failed）。`ChapterAudio` 维护两个指针 + 一个状态：
  - `desired_run_id`：最新期望运行（入队/恢复时指向最新创建的 `ChapterAudioRun`），驱动 `execution_status` 展示；
  - `published_run_id`：当前已发布产物所属运行，决定"可导出产物"；
  - `published_input_signature`：`published_run_id` 对应 `run_input_snapshot.input_signature`（幂等校验，发布时一并写入）；
  - `render_status`：**只描述 `published_run_id` 指向产物的状态**。
  规则：
  1. **入队/恢复时不触碰已发布状态**：新 run 创建时仅更新 `desired_run_id`，旧 `published_run_id`/`published_input_signature`/`render_status` 保持不变（旧产物仍可导出）。
  2. **输出文件落在 run 级路径（R7 修正）**：`build_chapter_audio_output_path` 增加 `run_id` 段（`audiobooks/project_{project_id}/audiobook_{audiobook_project_id}/run_{run_id}/chapter_{chapter_number:03d}.{ext}`），不同 run 的物理文件天然隔离——旧 run 晚完成时即使 CAS 未命中也不会覆盖新 run 的文件。
  3. **run 级输出登记（ChapterAudioOutput）**：成功写出文件后立即插入/更新登记行（`status='staged'`），未发布前不得被下载/试听链访问；**整章可导出字段不再由生成代码直接写**（现状 `apply_chapter_audio_generation_result` 直写 `audio_path`/`duration`/`file_size`、`generate_and_apply_subtitle_artifacts` 直写 `subtitle_path` 必须改为只写 run 级文件与 staged 登记，见 §1.5）。
  4. **完成时幂等完整发布（R8 修订）**：新 run 完成时在**一个事务**内原子执行（状态字段 + 整章元数据 + 输出登记 + artifact 状态机）。发布协议（解决完成回调重试缺陷——重试时 `desired_run_id` 仍等于当前 run_id，旧协议 ②③④ 会把本 run 已发布输出与 active artifact 再置 superseded 且无 staged 可恢复）：
     a. `SELECT ... FROM chapter_audios WHERE id = :chapter_audio_id FOR UPDATE`（锁定目标行，串行化同一章节的发布与并发判定）；
     b. **幂等短路**：若锁定的 `published_run_id = :run_id` 且 `published_input_signature = :signature` → **短路前最低一致性检查（R9，P2-1）**：确认存在 `status='published'` 的 `ChapterAudioOutput` 登记、镜像列（`audio_path`/`duration`/`file_size`）字段齐全且物理文件存在——全部通过才**直接返回成功**，不执行后续 SQL（覆盖 Celery 完成回调因超时/进程重启/ACK 丢失导致的重复执行）；任一不通过（登记缺失/字段残缺/文件丢失）**不短路**，按"产物损坏"报错并走 §8 修复流程（重新生成或人工登记），避免损坏后重复回调永远返回成功；
     c. **发布前置校验**（同事务内，任一不通过则回滚报错，不产生部分发布）：
        - run 归属与终态：`ChapterAudioRun` 存在且 `id = :run_id`、`chapter_audio_id = :chapter_audio_id`、`status = 'completed'`；
        - 可发布状态：**发布谓词按引擎解耦（R9，P0-2）**——`is_publishable_result(run)`：seed_scene 要求 `result_render_status ∈ {rendered_all_seed, rendered_with_fallback}`（`manual_review_required`/`failed` 不进入发布，见规则 5）；**legacy_stems（含 `chapter_remix`）要求 `result_render_status = 'completed'` 且整章输出文件齐全**（legacy 链路不产生 Seed 渲染状态，运行结束写 `completed`/`failed` 二值，§2.10——不再因 `result_render_status = null` 导致 legacy 全系无法发布）；
        - staged 输出恰一条：`SELECT count(*) FROM chapter_audio_outputs WHERE run_id = :run_id AND status = 'staged'` == 1；
        - artifact 完整性（seed_scene，R9/P1-4 增强）：该 run 的 staged artifact 集合与 checkpoint 场景列表 **`scene_id` 键集合全等**（`SET` 相等，非仅数量匹配）且**每场景恰一条 staged**（部分唯一索引防重复登记，§2.14）；逐条校验 `scene_topology_hash` 与 checkpoint 一致、`segment_keys` 非空且与场景归属一致、`content_digest` 与物理文件实际 sha256 一致（物理文件存在性检查）、`source_kind='legacy_fallback'` 的场景必须对应 checkpoint 回退记录（fallback 来源合同）——任一不符视为未完成装配；
     d. CAS 更新镜像列（下载链 `routes_download.py` 仍读 `ChapterAudio.audio_path`，该值只在本事务内被改写）：
     ```sql
     UPDATE chapter_audios
     SET published_run_id = :run_id,
         published_input_signature = :signature,
         render_status = :status,          -- seed_scene: rendered_all_seed | rendered_with_fallback
         audio_path = :audio_path,         -- run 级路径
         duration = :duration,
         file_size = :file_size,
         subtitle_path = :subtitle_path,
         subtitle_format = :subtitle_format
     WHERE id = :chapter_audio_id AND desired_run_id = :run_id;  -- CAS 含 id（R8）：rowcount == 0 立即结束，后续 SQL 一律不执行
     ```
     e. 旧输出 supersede（**显式排除本 run，R8**——重试场景下本 run 已 published 的行不被误置 superseded）：
     ```sql
     UPDATE chapter_audio_outputs SET status = 'superseded'
     WHERE chapter_audio_id = :chapter_audio_id AND status = 'published' AND run_id <> :run_id;
     ```
     f. 本 run 输出发布：
     ```sql
     UPDATE chapter_audio_outputs SET status = 'published', published_at = now()
     WHERE run_id = :run_id AND status = 'staged';
     ```
     g. artifact 状态机（**发布作用域 = `chapter_audio_id`（R8）**——同一源章节可存在于多个批次/引擎，裸 `chapter_id` 会把其他批次 active artifact 一并 supersede）：
     ```sql
     UPDATE scene_audio_artifacts SET status = 'superseded', deleted_at = now()
     WHERE chapter_audio_id = :chapter_audio_id AND status = 'active' AND run_id <> :run_id;
     UPDATE scene_audio_artifacts SET status = 'active'
     WHERE run_id = :run_id AND status = 'staged';
     ```
     h. 全部操作同一事务提交，任何一步失败整体回滚（镜像列/登记/artifact 不出现部分发布）。
     —— 旧任务晚完成不会覆盖新任务（d 的 CAS 不命中则全部跳过），新任务失败也不会破坏旧产物（c 的可发布状态校验不通过则不进入发布）。**seed 可发布状态集仅 `rendered_all_seed`/`rendered_with_fallback`**（`manual_review_required`/`failed` 不再进入发布 SQL——"失败不改变旧已发布产物"与"失败态可发布"直接冲突，见 §5 阶段 2.5；**legacy 引擎按 `result_render_status='completed'` 发布谓词，§2.4 规则 4 c/R9**）。
  5. 新 run 失败后旧成功产物的 `published_run_id`/`render_status` 不变（"自动回滚"：前端显示旧版本可用）；失败 run 的 staged 输出登记与 artifact 保持 staged（不可试听、不可导出），由 §8 清理策略回收。
  6. 并发渲染完成时以 `desired_run_id` 为 CAS 条件（上述 WHERE 子句原子完成），不再以 `render_status` 为 CAS 条件（`render_status` 现在只描述已发布产物，与"哪个 run 发布了产物"解耦）。
  7. **artifact 显式状态机（R7/R8）**：`SceneAudioArtifact.status ∈ {staged, active, superseded}`（§2.14）——仅用 `deleted_at` 无法区分"尚未发布"（staged）与"已被替代"（superseded）；激活/替代只在上述发布事务内随 `published_run_id` 切换，未发布的 run 的 artifact 绝不激活；**发布作用域 = `chapter_audio_id`（R8，§2.14 复合外键）**——同一源章节的其他批次/引擎的 artifact 不受本批次发布影响。
- `rendered_with_fallback` 的任务生命周期为 `succeeded`（`completed` 投影），仅通过 `render_status` 表示"完成但降级"。

**维度二：`published_render_status`（已发布产物渲染状态，seed_scene 新增持久化；API 投影自 `ChapterAudio.render_status`，R9/P1-5 唯一化；R11/P2-1 值域收窄）**

- **published 值域（R11/P2-1）**：`published_render_status ∈ {rendered_all_seed, rendered_with_fallback, stale, null}`——`manual_review_required`/`failed` 是**不可达态**（发布协议规则 4 c/5 保证二者不发布：首次失败 published=null、已有产物重渲染失败 published=旧成功值），published 值域不包含它们；
- **desired 值域**：`desired_render_status ∈ {rendered_all_seed, rendered_with_fallback, manual_review_required, failed, null}`（最新期望 run 的本次结果，可含人工评审/失败）；
- **result 值域（R11/P2-1）**：`result_render_status`（run 级结果）为 Seed **四态** `{rendered_all_seed, rendered_with_fallback, manual_review_required, failed}`——验收与测试表述统一为"Seed 四态"，不再称"五态"。

| 状态 | 定义 | 章节锁定 | 可打开编辑器 | 可导出 | 计费 | generatedChapterIds 收录 |
|------|------|---------|-------------|--------|------|------------------------|
| `rendered_all_seed` | 全部场景 `status == passed`（种子渲染，无回退） | 锁定（防覆盖生成） | 是 | 是 | 按 seed 价 | 是 |
| `rendered_with_fallback` | 存在 `legacy_stems` 回退场景，无 manual_review | 锁定（防覆盖生成） | 是 | 是（导出物标记"含回退场景"） | seed + 回退 TTS 拆分计价 | 是（降级标记） |
| `manual_review_required` | 存在人工评审场景，或按 `terminal_policy` 触发人工兜底 | 不锁定 | 是 | 否 | 已发生部分冻结 | 否 |
| `failed` | 渲染失败且无可用场景产物 | 不锁定 | 否（无产物） | 否 | 按失败政策（冻结已退还） | 否 |
| `stale` | 基线（script/topology/override 锚点）与当前事实失配，未重渲染 | 不锁定 | 是（只读基线对比） | 否 | 重渲染时重新计 | 否 |

- **值域归属（R11/P2-1）**：上表为完整状态语义表（含 desired 专属态）；**published 维度实际值域收窄为 {rendered_all_seed, rendered_with_fallback, stale, null}**——`manual_review_required`/`failed` 两行只出现在 `desired_render_status`（最新期望 run 的本次结果）与 `result_render_status`，发布协议（规则 4 c/5）保证二者永不发布（首次失败 published=null、已有产物重渲染失败 published=旧成功值），**published 值域不包含不可达态**；表格的"可导出/锁定/计费"列语义由 published 维度驱动（stale 不导出不计费；manual/failed 无 published 值可消费，由 desired 维度展示）。

- **锁定语义（R7 修正）**：`rendered_all_seed`/`rendered_with_fallback` 的"锁定"= **禁止覆盖式初始生成与直接修改已发布产物**，**允许创建 revision（台词/导演覆盖/音色编辑）与发起新 run（重渲染）**——锁定状态下的章节仍应进入场景编辑器提交 revision（与 §3.5 编辑器设计一致），前端仅禁用"覆盖式重新生成/直接改写已发布产物"的控件。

- `rendered_with_fallback` 是**完成但降级**（可导出、可计费），不是"非完成"；`manual_review_required`/`failed`/`stale` 才是未完成——R3 中"§2.10 称 rendered_with_fallback 为非完成"的表述已在 R5 统一为降级完成。
- `legacy_stems` 不产生 `chapter_render_status`（保持二值：`script_json + audio_path + script_status ∈ {reviewed, approved}`）；**其发布判定由 run 级 `result_render_status = 'completed'` + 整章输出文件齐全承担（R9/P0-2 发布谓词按引擎，§2.4 规则 4 c）**。

**持久化落点：**

- `ChapterAudio` 增加 `render_status`（String(32)，nullable，仅 seed_scene 批次非空，**值域 {rendered_all_seed, rendered_with_fallback, stale, null}——R11/P2-1 收窄：不存 manual_review_required/failed，首次失败/人工评审不发布时保持 null，已有产物重渲染失败保持旧成功值**）、`render_status_detail`（JSON，可选：`local_fallback_count`、`manual_review_scene_ids`、`stale_reason`、`terminal_policy`）与双指针列 `desired_run_id`/`published_run_id`（Integer，可空，**复合外键 `(desired_run_id, id) → chapter_audio_runs(id, chapter_audio_id)` / `(published_run_id, id) → chapter_audio_runs(id, chapter_audio_id)` ON DELETE RESTRICT——被当前指针引用的 run 行不可物理删除（R10/P1-1；R11/P2-2 归因修正："任何 run 只墓碑化"由 repository/service 层强制策略承担，§1.1），R8 单列外键升级（R9/P0-3），数据库层杜绝跨章节/跨实例指针**）、`published_input_signature`（String(64)，可空，§2.4 双指针发布模型）、**`published_provenance`（String(20)，可空：`published`（本次运行发布）| `legacy_unverified`（历史回填产物，仅展示/导出，不作 CAS 发布基线，R9/P1-1；R10 必须进入 API schema，P1-1））**。
- `ChapterAudioRun` 增加 **`chapter_audio_id`（Integer，不可变，外键 → `chapter_audios.id`，创建 run 时写入；复合唯一键 `(id, chapter_audio_id)` 替代 R8 的 `(id, audiobook_project_id, chapter_id)`——§2.4 运行作用域）**、**`result_render_status`（String(32)，可空：本次运行的结果状态，运行结束（无论是否发布）时写入，§2.4 三维投影；值域按引擎（R9/P0-2）：seed_scene ∈ {rendered_all_seed, rendered_with_fallback, manual_review_required, failed}（**Seed 四态，R11/P2-1**），legacy_stems 系（full/audio_from_scripts/chapter_remix）∈ {completed, failed}）与 `result_render_detail`（JSON，可空）**；**R11 派发与租约字段（P0-1/P1-1/P1-4）**：`celery_task_id`（String(128)，唯一，预生成固定 task id）、`predecessor_run_id`（Integer，可空，创建时持久化的上一 desired run id）、`dispatch_attempts`（Integer，非空默认 0）、`next_dispatch_at`（DateTime，可空）、`dispatch_claim_token`/`dispatch_claimed_at`（dispatcher 认领租约）、`claim_token`/`claimed_at`/`lease_expires_at`（worker 消费租约）——§1.1 迁移清单详列。
- **三维 API 投影（R8，解决"失败/人工评审结果无持久化位置"；R10 补 provenance 投影，P1-1）**：状态接口与 `SceneEditorDocument` 同时返回三个正交维度：
  - `published_render_status` = `ChapterAudio.render_status`（当前**可导出产物**状态；首次运行 `manual_review_required` 不发布时为 null）；
  - `desired_render_status` = `desired_run_id` 对应 `ChapterAudioRun.result_render_status`（**最新期望 run 的本次结果**；无 run 或未结束为 null——前端据此展示"最新一次已进入人工评审/失败"，不再误显旧版 `rendered_all_seed`）；
  - `execution_status` = desired_run_id 的任务生命周期（§2.4 维度一）。
  另返回 `published_provenance`（`published` | `legacy_unverified` | null，R10/P1-1）：**历史回填产物与任何 `legacy_unverified` 状态必须进入 API schema**——消费者将 `published_provenance='legacy_unverified'` 且 `published_render_status=null` 的产物显式渲染为"历史产物（未验证）"，**不允许把未知 fallback/manual 历史误读为全 Seed 成功**（历史 seed 产物不再回填精确 `rendered_all_seed`，见 §1.1 迁移清单）。
  状态表的"可导出/锁定/计费"列由 `published_render_status` 驱动（**published 值域四值 {rendered_all_seed, rendered_with_fallback, stale, null}，R11/P2-1**）；"进行中/本次结果"由 `desired_render_status` + `execution_status` 驱动。
- `render_status` 由章节渲染**发布成功时**按 §2.4 双指针模型聚合写入（`WHERE desired_run_id = :run_id`）；**入队/恢复/重渲染不前置清空**（旧已发布产物保持可导出，见 §2.4）；`execution_status` 不新增列，继续由 `ChapterAudioRun.status` 聚合投影。
- 导出与计费判定读 `render_status`；**锁定判定（R7 修正）** = `render_status ∈ {rendered_all_seed, rendered_with_fallback}` 时禁止覆盖式初始生成与直接修改已发布产物，**允许创建 revision 与发起新 run**（前端禁用"覆盖式重新生成/直接改写已发布产物"控件，场景编辑器保持可用，§3.5）。

**`auto` 归一化规则**（批次创建前解析，冻结值不含 auto）：

```
resolve_engine_mode(config):
  mode = get_audio_engine_mode(config)
  if mode != "auto": return mode
  if engines.seed_scene 分支非空（tts_models / scene_generation_preferences 任一）
     or 旧顶层存在任一 seed 键（seed_timeline_mode / seed_terminal_policy / semantic_review_*）:
    return "seed_scene"
  return "legacy_stems"
```

- 章节"已生成"判定仅统计 `engine_mode == 当前引擎` 的批次（§2.1 组合索引支撑）。
- `seed_scene` 模式下生成了第 1 章，切换到 `legacy_stems` 后，第 1 章显示为"从未生成过"；切回 `seed_scene` 恢复。两套状态完全独立共存，不互相清除。

### 2.5 章节编辑器按引擎分流

点击已生成章节时按该章节所属批次的 `engine_mode` 分流：

- `legacy_stems` → 现有剧本编辑器（`useAudiobookScriptEditorActions.handleOpenScriptEditor`）。
- `seed_scene` → 新建独立场景编辑器（见阶段 3）。

**多批次选择规则**（同一章节存在多个同引擎批次时，替换现有"取第一个"逻辑）：

1. 优先**已发布产物**的批次（`published_run_id` 非空且 `render_status ∈ {rendered_all_seed, rendered_with_fallback}`，按 `updated_at` 降序）；
2. 其次最新创建批次；
3. 编辑器内提供**批次切换器**，允许用户显式选择要查看/编辑的批次（列表来自 `list_audiobook_projects` 的 engine_mode 过滤结果）。

### 2.6 三类场景编辑 revision 分离（含稳定锚点与传递链）

场景编辑按编辑类型分为三类 revision，使用不同的接口与失效范围：

| 编辑类型 | 事实性质 | 应失效的层级 | 存储目标 | 是否修改 script_json |
|---------|---------|-------------|---------|-------------------|
| 台词/说话人 | 审定剧情事实 | Script review → Director → Binding/Planner → Seed → L0 → Omni | `script_json`（经审定剧本修订接口） | 是 |
| 表演/音效/音乐 | Scene direction override | Director 输出或 Prompt → Seed → L0 → Omni | `SceneEditRevision`（edit_type=director_override 的 payload） | 否 |
| 音色绑定 | Voice identity/binding | Binding → Seed → L0 → Omni | `SceneEditRevision`（edit_type=voice_binding）+ `Project.audio_config.engines.{mode}.tts_models.{model}.characters`（双写，§2.6 当前章节局部覆盖 + 未来批次默认值） | 否 |

- 台词编辑走既有剧本审定与保真审计通路，更新 `script_json` 后使源事实 hash 变化，Director/Seed/L0/Omni 签名失配，重渲染时自然重算所有层级。
- 导演覆盖不写入 `ScriptSegment.text`；**`SceneDirectionOverride` 不建独立表**，完全由 `SceneEditRevision` 链（edit_type=director_override 的 payload）投影得到——避免双写不一致，`SceneEditorDocument.editable_overrides` 从链尾反向合并计算。
- 音色绑定走音色管理面板，不涉及剧情或导演指令。**作用域语义（R7 收敛为"当前批次当前章节局部覆盖"）**：voice_binding 编辑**只对当前章节的 revision 链生效**（写入 `SceneEditRevision`，edit_type=voice_binding，记录本次变更事实与 head 投影），并**同时更新** `Project.audio_config.engines.{mode}.tts_models.{model}.characters` **仅作为未来批次的默认值**。确定性预期：①当前章节通过该 revision 链使用新音色（重渲染时生效）；②同批次其他章节的 `run_input_snapshot` 已冻结旧音色，重渲染仍得旧音色，不受影响；③未来批次从项目配置读取新音色。**仅当前章节的已发布产物置 stale**（`stale_reason = voice_binding_changed`），同批次其他章节不置 stale——它们的快照与绑定仍然自洽（旧音色、旧绑定一致），置 stale 反而无法通过重渲染消除（R7 修正：全项目 stale 与冻结快照自相矛盾）。**全项目改音色需要显式创建新批次**（新批次从项目配置读取新音色）或为每个目标章节逐个提交 voice_binding revision；不引入全局 voice revision 表（YAGNI）。不允许只写 revision 不写项目配置（会造成"当前章节与未来默认值分裂"），也不允许只写项目配置不写 revision（无法审计变更）。**并发锁（R9，P1-6）**：voice_binding 双写（`SceneEditRevision` + `Project.audio_config` 分支）必须在**同一事务**内完成，且先 `SELECT ... FROM projects WHERE id = :project_id FOR UPDATE` 锁定 Project 行（或对 `audio_config` 配置版本做 CAS，R9 采用行锁）再读改写 `audio_config` + 写 revision + 更新 head + 置 stale——不同章节并发提交 voice_binding 时后提交者覆盖前者的配置写入被串行化（后者在前者提交后才读改写，不会静默覆盖），任一步失败整体回滚，不产生"revision 已写、配置未写"或反向的分裂状态；

**`segment_key` 落地（当前 `ScriptSegment` dataclass 无此字段）：**

1. `script_adapter_pkg/_dataclasses.py` 的 `ScriptSegment` 增加 `segment_key: str = ""`；`build_script_segment`（dict → dataclass）从 `script_json` 字典带入（`routes_script._sanitize_incoming_script_segments` 已为 script_json 字典补齐 `segment_key`，dataclass 层同步补齐）。
2. 传递链（从脚本到渲染的每一层都携带）：`script_json dict` → `ScriptSegment dataclass` → `ScenePlanner`（`source_segment_indices` 之外同时保存 `source_segment_keys` 有序元组）→ `SceneRenderPlan`/`SceneDirection` → `SceneRenderResult`/checkpoint（每场景记录 `segment_keys`）。
3. split 派生场景（`_split_{n}`）继承对应半段的 `source_segment_keys`，不重新编号。
4. `scene_topology_hash` canonical 合同：

```
scene_topology_hash = sha256(canonical_json([
  {"scene_id": ..., "source_segment_keys": [...], "segment_count": n}, ...
]))
# canonical_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

5. 归属一致判定：override 锚点场景的 `source_segment_keys` 与当前规划中同一 scene_id 的 keys **完全相等** → 跟随；全部存在但归属变化 → 标记 stale 要求重新绑定；部分缺失 → stale。

**override 稳定锚点结构**（存入 revision payload）：

```jsonc
{
  "scene_id": "scene_0003_split_01",
  "stable_anchors": {
    "source_segment_keys": ["seg_a1b2c3", "seg_d4e5f6"],
    "baseline_script_revision_hash": "sha256:...",
    "baseline_scene_topology_hash": "sha256:..."
  },
  "overrides": [{"direction_type": "performance"|"sfx"|"music"|"acoustic", "content": "..."}]
}
```

- 匹配/失效逻辑与场景重渲染的"仅重算受影响场景"共用同一锚点判定，避免覆盖失效与渲染失效两套规则漂移。

### 2.7 引擎切换不清空数据

切换引擎不清空对方引擎的章节产物与角色绑定数据，两套数据完全独立共存。

### 2.8 生成编排隔离（分流点前移，禁止范围收窄）

两引擎在公共事实层之后立即分流，不共享导演策略、素材准备、渲染编排、质量评审或 checkpoint 类型。

**公共生命周期**（可复用）：

- 章节原文与角色档案加载
- `engine_mode` 确定与冻结（`resolve_engine_mode` + 配置快照写入批次，§2.1/§2.4）
- `AudiobookProject`/`Run` 创建（带 `engine_mode`、配置快照与 `run_input_snapshot`）
- 审定 `ScriptFacts` 构造（`ScriptSegment[].text` + `speaker` 归属 + `segment_key` + 原文保真）

**分流点位置（关键约束）：**

> 分流必须在**旧 AudioDirector 策略制定与 `_parallel_design` 之前**完成。当前 `_generation_mixin.generate_chapter_audio`（约 114 行）与 `_audio_from_script_mixin`（约 80 行）在调用 Seed 场景管线前已无条件执行 `AudioDirector.formulate_strategy()` + `_apply_audio_fx_to_strategy()`，仅修改 `_parallel_mixin.prepare_render_assets` 默认值属于"晚分流"，不足以隔离。R5 起在两条 mixin 的入口（`formulate_strategy` 之前）按 `engine_mode` 分流：`seed_scene` 直接进入场景导演链路。

```
legacy_stems:
  ─► LegacyAudioDirector（风格策略 + audio_fx 密度）
  ─► 分轨 ScriptSegment 合同
  ─► 逐句音色分配（VoiceManager）
  ─► TTS 片段生成
  ─► SoundEffectDesigner / MusicComposer / Mixer
  ─► 分轨技术质量检查
  ─► 片段/分轨工作台

seed_scene:
  ─► SeedSceneDirector（不运行旧 AudioDirector 的音效/配乐密度策略）
  ─► SceneDirection / VoiceIdentityRegistry / SceneVoiceBindingPlanner
  ─► ScenePlanner / ScenePromptCompiler
  ─► Seed Audio multilingual 逐场景渲染
  ─► L0 + Omni 影子评审
  ─► SceneAudioAssembler 场景拼接（首尾拼接 + 整章时轴 + 字幕，允许且必需）
  ─► 场景音频登记 SceneAudioArtifact（正式 artifact 存储，§2.14）
  ─► 场景编辑器
  ─► 失败 → 受控 legacy fallback（按失败场景延迟生成回退素材）
```

**编排层隔离约束：**

- `seed_scene` 入口不调用 `AudioDirector.formulate_strategy()`；不传递 `sound_effect_density`/`music_density` 等旧策略参数到任何下层。
- `seed_scene` 成功路径**禁止的是旧分轨 `Mixer`、`SoundEffectDesigner`、`MusicComposer` 和逐句 TTS**；`SceneAudioAssembler`（`scene_engine/scene_assembler.py`）承担的场景结果拼接、整章时轴与字幕生成**不属于**禁止范围，是 seed_scene 成功路径的必需环节。
- `prepare_render_assets` 由管线自身根据 `engine_mode` 决定（`engine_mode == 'seed_scene'` → 恒 False），不依赖调用方传参。
- legacy fallback 是 `seed_scene` 的显式失败动作，按 `FallbackAssetPlan` 按场景延迟生成（`_scene_render_mixin._render_legacy_scene_fallback`），不是正常路径预生成。
- 两管线使用不同的 stage graph、progress event 和 checkpoint 类型（§2.12）。

### 2.9 checkpoint append-only 与 SceneEditRevision 双表设计（原子并发）

Seed checkpoint（`ChapterAudioRun.checkpoint_json`）包含真实供应商请求与 Request ID、已生成 artifact、attempt 与计费事实、Director/Seed/L0/Omni 结果与签名、Provider recovery 状态、人工评审证据。**任何场景编辑不得删除或覆盖现有 checkpoint。**

编辑历史使用 **独立双表**（解决“声明 append-only 又要求 UPDATE is_head”的矛盾）：

**表一：`scene_edit_revisions`（严格 append-only，无 is_head 列，禁 UPDATE/DELETE）**

```python
# backend/app/models/audiobook.py（经 Alembic 创建）
class SceneEditRevision(Base):
    __tablename__ = "scene_edit_revisions"
    id = Column(Integer, primary_key=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    base_run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=True)
    parent_revision_id = Column(Integer, nullable=True)    # 链前驱（R7：单事实表示，不存 parent_revision_hash，hash 经 JOIN）
    edit_type = Column(String(32), nullable=False)               # dialogue | director_override | voice_binding
    payload = Column(Text, nullable=False)
    affected_anchors = Column(Text, nullable=True)
    input_signature = Column(String(64), nullable=False)         # payload 内容的规范化签名（幂等去重）
    revision_hash = Column(String(64), nullable=False)           # 链节点签名（含父引用），全表唯一
    operator_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("revision_hash", name="uq_scene_edit_revision_hash"),
        # 复合唯一键：供 head 表与自引用 parent 外键引用作用域（R7 新增）
        UniqueConstraint("id", "audiobook_project_id", "chapter_id", "edit_type",
                         name="uq_scene_edit_revision_scope"),
        # 自引用复合外键：parent 必须与子行同 (project, chapter, edit_type)，
        # 数据库层杜绝"跨章节/跨链挂父引用"（R7 新增）
        ForeignKeyConstraint(
            ["parent_revision_id", "audiobook_project_id", "chapter_id", "edit_type"],
            ["scene_edit_revisions.id", "scene_edit_revisions.audiobook_project_id",
             "scene_edit_revisions.chapter_id", "scene_edit_revisions.edit_type"],
            name="fk_scene_edit_revision_parent_scope",
        ),
    )
```

> **parent 单事实表示（R7 修正）**：只保留 `parent_revision_id`，不再存 `parent_revision_hash`——与 R6 对 head hash 的处理同构：同表保存 ID 与 hash 时数据库无约束保证两者指向同一条 revision，存在内部不一致风险；`parent_revision_hash` 通过 `parent_revision_id` JOIN `scene_edit_revisions.revision_hash` 获得。

**表二：`scene_edit_revision_heads`（每 (project, chapter, edit_type) 一行，可 UPDATE，提供稳定行锁）**

```python
class SceneEditRevisionHead(Base):
    __tablename__ = "scene_edit_revision_heads"
    id = Column(Integer, primary_key=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    edit_type = Column(String(32), nullable=False)               # dialogue | director_override | voice_binding
    head_revision_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("audiobook_project_id", "chapter_id", "edit_type", name="uq_scene_edit_head"),
        # 复合外键：head 指向的 revision 必须与 head 行同 (project, chapter, edit_type)，
        # 数据库层杜绝"本章节 head 指向另一章节/另一链的 revision"（R7 新增）
        ForeignKeyConstraint(
            ["head_revision_id", "audiobook_project_id", "chapter_id", "edit_type"],
            ["scene_edit_revisions.id", "scene_edit_revisions.audiobook_project_id",
             "scene_edit_revisions.chapter_id", "scene_edit_revisions.edit_type"],
            name="fk_scene_edit_head_revision_scope",
        ),
    )
```

> **head 表只存 `head_revision_id`，不存 `head_revision_hash`**——hash 通过 `head_revision_id` JOIN `scene_edit_revisions.revision_hash` 获得。同表同时保存 ID 与 hash 时数据库无约束保证两者指向同一条 revision，存在内部不一致风险；单列 + JOIN 消除该问题。head 的作用域由**复合外键**（`head_revision_id` + project + chapter + edit_type 引用 revision 表复合唯一键）在数据库层保证，不再依赖应用层校验。

**revision_hash 确定性计算公式（与 input_signature 的区分）：**

- `input_signature = sha256(canonical_json({edit_type, payload, affected_anchors}))` —— 只覆盖编辑内容，用于幂等去重（相同内容重复提交返回原 revision）。
- `revision_hash = sha256(canonical_json({audiobook_project_id, chapter_id, edit_type, payload, affected_anchors, parent_revision_hash}))` —— 覆盖整条链位置，父引用变更即产生新节点；其中 `parent_revision_hash` = 父行（`parent_revision_id` 经 JOIN）的 `revision_hash`，无父时为空串。
- canonical_json 统一为 `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。

**幂等判定（先算候选、后锁比对，闭环；R7 修正）：**

1. **候选 hash 以请求携带的 `base_revision_hash` 为 parent 计算**：`candidate_hash = sha256(canonical_json({audiobook_project_id, chapter_id, edit_type, payload, affected_anchors, request.base_revision_hash}))`（无 base 时 parent 项为空串）。**不使用当前 head 的 hash 参与候选计算**——同一请求的候选 hash 在任何时刻都是确定值，与 head 是否已推进无关；若按"当前 head 的 parent hash"计算，首次写入后 head = H = hash(payload, P)，同一请求重试会算出 H2 = hash(payload, H) ≠ H，幂等短路不命中且 base 比对 P ≠ H 必 409（R7 修复该缺陷）。
2. 锁住 head（FOR UPDATE，见下）后按序判定：
   - **幂等短路**：若锁定的 head 的 `revision_hash == candidate_hash`（相同内容、相同父引用），直接返回该 head revision（幂等成功），不插入新行、不触发 base 比对——覆盖同 base 上的重复提交/网络重试/并发双端同请求。
   - 否则比对 `request.base_revision_hash` 与锁定的 head `revision_hash`：不匹配 → `409 Conflict`（返回当前 head revision_hash，客户端刷新后按新 head 为 base 重新计算提交）——head 已被其他编辑推进时的正确行为。
   - 匹配 → 插入新 revision（`parent_revision_id` = 当前 head 行），并更新 head 行的 `head_revision_id`（更新可控、无碍 append-only 的 revision 表）。
3. **跨 head 推进的幂等（可选增强）**：若要求"head 已被后续编辑推进后，对原请求仍返回原成功结果"（而非 409），必须引入独立持久化 `idempotency_key`（客户端生成请求 UUID；服务端持久化 `(idempotency_key, revision_id)` 映射并唯一约束，命中即返回原 revision）——**不能只依赖当前 head**（head 只保存链尾一个指针，无法回答"某次历史请求的结果是什么"）。默认实现采用链式并发语义（head 推进后重试 409，客户端刷新），idempotency_key 作为前端防重复提交的增强项可选落地。

**全局锁序（R10，P1-4，消除编辑/审批死锁；R11 账户锁置顶，P0-2）**：所有入队冻结、编辑、审批与 run 快照捕获路径必须遵守同一加锁顺序：**`pg_advisory_xact_lock(user_id)`（积分冻结事务开头，账户级资金不变量，R11/P0-2）→ `Project`（需要时，如 voice_binding 双写）→ `ChapterAudio` 行 → dialogue head → director_override head → voice_binding head**。普通 revision 编辑在锁 head 之前**先锁 `ChapterAudio` 行**（与审批一致）；审批先锁 `ChapterAudio` 再按固定顺序锁三条 head——若编辑锁 head → 后写 ChapterAudio、审批锁 ChapterAudio → 后锁 head，两事务交叉即形成 head→ChapterAudio 与 ChapterAudio→head 的经典死锁；统一锁序后消除。**冻结事务的账户锁位于锁序最前端**（冻结事务只持账户锁 → ChapterAudio，不涉及 head，与编辑/审批路径无交叉环；任何路径不得在账户锁之前加锁）。**账户锁的收敛前提（R12/P0-3）**：`pg_advisory_xact_lock(user_id)` 只在"所有会改变同一用户余额或冻结额的路径都使用同一锁键"时才能保证账户级不变量——通用冻结入口 `record_points_billing_freeze`（`user_center_points_events.py` 约 372 行）现状无锁，拆书（`book_parser.py` 约 254 行）、小说协同扩展（`workflow/routes_expand.py` 约 649 行）、短剧独立冻结路径（`dreamweaver_tasks_pkg/_task.py` 约 414 行）与管理员积分调整（`admin/users.py` 约 396 行）都是独立写路径；**必须将"用户积分账面变动 + 余额/冻结校验"收敛到共享 points mutation service**——任何冻结、结算、释放、管理员调账及影响可用余额的业务事件都经该 service 并在同一 advisory 锁键下执行（`record_points_billing_freeze`/`record_points_billing_settle`/release、管理员积分调整、短剧 `record_dreamweaver_billing_freeze` 全部改为调用共享 mutation service 的锁内入口）；收敛完成前，有声书锁内重聚合无法排除其他路径在"锁内重聚合之后、冻结提交之前"写入积分事件造成的超额冻结，**不得宣称维持用户账户级不变量**。真实 PostgreSQL 并发测试必须覆盖编辑×审批交叉路径、**双请求并发超额冻结**与**计费域双路径同锁序**（会话 A：worker 终态主路径 × 会话 B：人工收敛/其他账户 mutation 路径，断言两条路径加锁顺序完全相同、无死锁，R19/P0；§7）。**计费域锁序（R19/P0；R20/P1-1 纳入 ledger 行；R21/P2-1 精确化：三层锁序 + 锁内写入顺序）**：一切涉及 run 级计费结算的路径（worker 执行终态写协议、统一 finalizer、人工收敛、`billing_finalizer_scan`）必须按同一三层锁序加锁：**① `pg_advisory_xact_lock(billing_account_user_id)`（账户锁）→ ② `ChapterAudioRun` 行 `FOR UPDATE` → ③ `BillingUsageLedger` 行 `FOR UPDATE`（涉及多条时统一按 `ledger.id` 升序加锁，禁止无序）**——仅这三项是需要统一排序的竞争资源；持锁后的**锁内写入顺序**统一为：ledger 状态更新 → 必要时插入 `LedgerReconciliationAudit` → strict barrier → 置 `billing_finalized_at` 封口 → settle 事件写入（单次 commit）。**audit INSERT 不是锁层级**：它是新行插入、不构成行锁竞争，也不是所有路径都执行——`LedgerReconciliationAudit` 仅用于人工收敛路径（记录 from/to/operator/evidence），worker 正常成功转态、confirmed_failed 自动关账与纯 finalizer 重试不插入 reconciliation audit。禁止式合同：**任何路径必须先取账户锁再取 run 行锁，禁止先取 run 行锁再取账户锁；任何路径禁止在账户锁与 run 行锁之前按 `ledger_id` 查询或 `FOR UPDATE` ledger（收敛入口按 ledger_id 以不加锁的普通 SELECT 解析所属 run，再按上述顺序取锁）——两种反序均会形成死锁环（事务 A 持账户+run 锁等 ledger 锁、事务 B 持 ledger 锁等账户锁）**（§2.1 执行终态写协议、§8.5）。作用域界定：约束对象是**既有 ledger 行的 UPDATE/SELECT FOR UPDATE**；建账写 pending ledger 为 INSERT 新行，不构成行锁竞争；只读 barrier 查询若伴随状态更新，必须在持有 run 行锁后执行。worker 建账短事务仅持 run 行锁（不取账户锁、不锁既有 ledger 行，无锁序反转）；同一 run 的多 ledger 更新（worker 终态关账等）必须按稳定主键（`ledger.id` 升序）加锁。

**原子并发控制（防分叉链：在 head 表执行 FOR UPDATE，解决"首次编辑时 SELECT 锁不到不存在行"问题）：**

1. 事务内 **① `SELECT ... FROM chapter_audios WHERE id = :chapter_audio_id FOR UPDATE`（R10/P1-4，编辑/审批域业务行锁第一步；R18/P2-3 澄清：与 §2.9 全局锁序“账户锁置顶”不矛盾——账户 advisory 锁是全局跨域最顶层锁，涉账户资金的事务必须先取账户锁，ChapterAudio 行锁是进入业务行锁域后的第一步）** → ② `SELECT ... FROM scene_edit_revision_heads WHERE audiobook_project_id=? AND chapter_id=? AND edit_type=? FOR UPDATE`（行锁，PostgreSQL READ COMMITTED 即可，无需 SERIALIZABLE）。
   - 若行不存在（首次编辑）：插入新 revision + head 行。
2. 幂等短路与 base 比对按上述顺序执行。
3. **并发 loser 处理（R8：SAVEPOINT 恢复协议；R9 精确写法，P2-2）**：PostgreSQL/SQLAlchemy 中唯一约束冲突会把当前事务置为 **aborted** 状态——未 rollback 或未退出 SAVEPOINT 前不能继续任何查询（旧表述"捕获 `IntegrityError` 后直接重读 head"在真实 PG 下会抛 `InFailedSqlTransaction`）。必须：
   - **SAVEPOINT 精确写法（R9，P2-2）**：`nested = session.begin_nested()`（SAVEPOINT）包住首次 revision/head 插入；捕获 `IntegrityError` 后调用 `nested.rollback()`（**仅回滚到 SAVEPOINT，外层事务保持可用**），**再重读 head**——若 head 的 `revision_hash` 与自身请求的 `candidate_hash`（以请求 `base_revision_hash` 计算）相等，返回幂等成功；否则返回 `409 Conflict`（同一请求双端同时提交不产生错误，不同请求才冲突）。**严禁 `session.rollback()`——它终止整个外层事务而非仅 SAVEPOINT**（错误实现会把同事务已完成的 head 锁与写入一并回滚并抛 `PendingRollbackError`）；亦可用 `with session.begin_nested():` 上下文管理器，`IntegrityError` 时自动回滚到 SAVEPOINT；或
   - 回滚整个事务后开启新事务重读 head（更重，仅在不支持 SAVEPOINT 的环境使用）。
   - 测试计划必须覆盖**真实 PostgreSQL 下的双事务并发路径**（两个会话同时提交同 base），而非仅模拟 `IntegrityError`（§7）。

**三条链的确定性投影与 SceneEditorDocument 消费：**

基于 edit_type 分组，实际存在三条独立链（dialogue / director_override / voice_binding）。`SceneEditorDocument` 的 `last_revision` 应为三个 head 的完整投影，而非单一未定义的“最近 revision”：

```python
# SceneEditorDocument
last_revisions: dict = {
    "dialogue": "<head revision_hash> | None",
    "director_override": "<head revision_hash> | None",
    "voice_binding": "<head revision_hash> | None"
}

revision_set_hash = sha256(canonical_json(last_revisions))
```

- `run_input_snapshot` 消费的也是三个 head 的确定性投影，不是单一未定义的“最近 revision”。
- `ChapterAudioRun` 新增 `revision_set_hash`（String(64)）列代替原来的 `revision_hash`，用于区分同一章节同一 `run_type` 的不同编辑运行。

**旧剧本接口统一拒绝（防绕过并发链）：**

- `PUT /audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/script`（`routes_script.py`）对 **seed_scene 批次禁止直接写 `script_json`**：统一返回 `409/400`（提示走场景编辑器），不委托到 edit_type=dialogue（委托需定义完整的请求体转换、事务边界和响应格式，成本较高且存在绕过风险）。legacy_stems 批次保持现状（无场景链，不强制 revision）。
- dialogue 编辑提交后（经场景编辑器，接口见 §3.2），若语义指纹变化（`_script_semantic_fingerprint` 不等）：**自动重置 `script_status = 'pending'`**，并清空 `script_review_json`、`final_audio_review_json`、`segment_reviews_json`；同时新 revision 的 `affected_anchors` 包含全部受影响 `segment_key`。

**dialogue 审批闭环（R8 新增，解决"编辑 → pending → 旧审批入口被拒 → 重渲染要求 approved → 无法继续"死锁）：**

- **新端点 `POST /audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/dialogue-review`**（`routes_scene_editor.py`）：seed_scene 批次 dialogue 链的独立审批入口（旧 `PUT /script` 的 `script_status` 写入口对 seed_scene 被拒，`routes_script.py` 约 511 行现状是唯一可设 pending/reviewed/approved 的入口，必须由本端点承接）。
  - **请求体**：`{verdict: "reviewed" | "approved", review_json: {...}, base_revision_set_hash: "<三类 head 投影 hash，§2.9>"}`；
  - **并发基线（R9 锁后重算协议，P1-2，修复 TOCTOU；R10 全局锁序，P1-4）**：审批事务按固定顺序加锁——①`SELECT ... FROM chapter_audios WHERE id = :chapter_audio_id FOR UPDATE`（锁章节行）→ ②按固定顺序（dialogue → director_override → voice_binding）`SELECT ... FROM scene_edit_revision_heads WHERE audiobook_project_id=? AND chapter_id=? AND edit_type=? FOR UPDATE` 锁三条 head（**与普通编辑路径共用全局锁序（冻结事务额外先取 `pg_advisory_xact_lock(user_id)` 账户锁，§2.9/R11/P0-2）：`Project → ChapterAudio → dialogue head → director head → voice head`，消除 head→ChapterAudio 与 ChapterAudio→head 交叉死锁，R10/P1-4**）→ ③**锁后重算** `revision_set_hash`（锁后值）与 `_script_semantic_fingerprint`（读锁定的 `script_json`）→ ④与请求 `base_revision_set_hash` 比对（失配 `409`）→ ⑤原子写审核证据（`script_review_json`/`script_review_version`/`script_status`）——READ COMMITTED 下审批读旧 head、并发编辑提交、审批再提交把新剧本误标 approved 的窗口被消除（读取与比对必须在同一事务内完成，不能先读后开事务）；
  - **状态机**：`pending → reviewed → approved`——仅当当前 `script_status ∈ {pending, reviewed}` 且语义指纹与提交审核时一致才允许迁移；`verdict=approved` 且处于 reviewed 才置 `script_status='approved'`（不允许 pending 一步直达 approved，除非 `verdict=reviewed` 与 `approved` 同次提交，见下）；
  - **一次性直批**：请求体可同时携带 `verdict="approved"` + `review_json`（跳过中间 reviewed 展示态），等价于 pending → reviewed → approved 原子迁移；
  - **审核证据持久化**：`review_json` 写入 `ChapterAudio.script_review_json`（复用既有字段），审核版本写入新增 `script_review_version`（String(64)，自增/时间戳，§1.1 迁移清单），与 §2.1 复制合同的 `source_script_review_version` 语义一致（复制时携带源审核版本）；
  - **审核后再编辑**：dialogue 语义变化 → 重置 pending 并清空 `script_review_json`/`script_review_version`（重新走审核，不允许携带旧审核证据重渲染）；
  - **重渲染门槛**：`audio_from_scripts`/场景重渲染创建 run 时要求 `script_status='approved'`（§2.1 run_type 合同）——审批通过后即可发起重渲染，死锁解除；
  - legacy_stems 批次不使用该端点（保持旧 PUT /script 的 pending/reviewed/approved 语义）。
- 编辑链不产生新 checkpoint；重渲染由既有章节生成任务接口承接，以 `revision_set_hash` + `run_input_snapshot` 为新运行输入（新 `ChapterAudioRun`，run_type 保持不变，见 §2.10）。

### 2.10 run_type 语义与引擎独立完成条件

`ChapterAudioRun.run_type` **保持既有语义**——表示"做什么操作"，恢复优先级（`task_support.RESUME_RUN_TYPE_PRIORITY`）、检查点选择与既有查询依赖该值，不得改写为引擎名（**R8：代码中还存在 `chapter_remix` 与 `segment_candidate` 两种 run_type，见下分类，文档不再声称只有三种**）。

- "由哪个引擎执行"由 `audiobook_project.engine_mode`（不可变）表达。
- `ChapterAudioRun` 增加不可变 `engine_mode_snapshot`（String(20)，创建运行记录时从批次复制）、`run_input_snapshot`（Text）、`revision_set_hash`（String(64)，本次运行的编辑基线）与 `input_signature`（String(64)），**不复用 run_type**。

| 维度 | legacy_stems | seed_scene |
|------|-------------|-----------|
| 章节成功 | script_json + audio_path + status ∈ {reviewed, approved} | `render_status ∈ {rendered_all_seed, rendered_with_fallback}`（§2.4） |
| 场景成功 | 不适用（无场景级状态） | SceneRenderResult.status ∈ {passed} |
| 局部回退 | 不适用 | 失败场景按 terminal policy 执行 legacy fallback；render_status 聚合为 rendered_with_fallback（完成但降级）或 manual_review_required |
| 章节进行中 | run_type=script_only/full/audio_from_scripts，engine_mode=legacy_stems | run_type 同上，engine_mode=seed_scene（stage graph 不同） |

**run_type 分类（R8 明确：可发布/可计费生成 run vs 辅助 run，各自快照合同）：**

| 类别 | run_type | 产生整章产物 | 走发布事务 | 计费 | 快照合同 |
|------|---------|------------|----------|-----|---------|
| 可发布生成 run | `script_only` | 否（仅剧本） | 否 | 是（剧本生成计费） | §2.1 run_type 合同（冻结原章输入，恢复依赖 checkpoint） |
| | `full` | 是 | 是 | 是 | §2.1（冻结原章输入 + **checkpoint 内 `generated_script_facts` 剧本正文，R8**） |
| | `audio_from_scripts` | 是 | 是 | 是 | §2.1（冻结 `script_facts` 正文） |
| | `chapter_remix`（`routes_remix.py`，legacy_stems 人工整章重混） | 是 | **是（R8 纳入发布体系）** | 是（按重混用量计费） | 冻结源已发布 run 的 `input_signature` 基线 + 混音参数（不重新生成剧本） |
| 辅助 run | `segment_candidate`（`segment_candidate_registry.py`） | 否（候选片段临时资产） | 否 | 否 | 不冻结完整 `run_input_snapshot`（checkpoint 存缓存路径与 TTL），不可恢复为正式运行，TTL 过期回收 |

- `chapter_remix` 输出同样落 run 级路径 + `ChapterAudioOutput`（staged）+ §2.4 规则 4 发布事务（**发布谓词按 legacy 引擎：`result_render_status='completed'` + 整章输出文件齐全，§2.4 规则 4 c/R9/P0-2**）——**必须删除 `background_jobs_remix.py` 现有"输出路径变化时 `_cleanup_previous_chapter_artifacts` 直接回收旧整章产物"（约 744 行）与直写 `ChapterAudio.audio_path`/`duration`/`file_size`/`subtitle_path`（约 768 行）的路径**，旧产物回收改由发布事务 supersede + §8 清理策略承担——否则人工重混可删除当前已发布文件、绕过 R7/R8 原子发布保证（§1.5）。
- **`result_render_status` 值域按引擎（R9，P0-2）**：seed_scene 运行 ∈ {`rendered_all_seed`, `rendered_with_fallback`, `manual_review_required`, `failed`}（与 `chapter_render_status` 聚合语义一致）；legacy_stems 系（`full`/`audio_from_scripts`/`chapter_remix`）∈ {`completed`, `failed`}（legacy 链路不产生 Seed 渲染状态，运行结束写入二值）；`segment_candidate` 不写该字段。发布谓词（§2.4 规则 4 c）按引擎消费各自值域，杜绝"legacy 因 `result_render_status = null` 无法发布"。
- `segment_candidate` 不入计费与发布链路：无 `ChapterAudioOutput`、无发布事务、无 billing_snapshot；`execution_status` 正常展示，但 `result_render_status`/`published_render_status` 恒为 null。

### 2.11 恢复任务只消费运行输入快照（方案 A，按 run_type 合同）

- **执行/恢复阶段禁读实时数据（R7 边界）**：恢复/续跑任务**只消费运行记录 `run_input_snapshot`（方案 A 自包含正文：引擎配置 payload + 剧本事实/原章输入 + 音色解析 + 编辑基线投影 + 运行参数 + 策略与计费）**，不读取项目当前 `audio_engine_mode`、`engine_config_snapshot` 或 `ChapterAudio.script_json` 实时值——**快照捕获发生在运行创建阶段**（§2.1 run_type 合同），执行与恢复阶段不再有任何读取实时数据的路径。`_scene_render_mixin._resume_model` 已实现"历史 checkpoint 按原始模型恢复"原则，engine_mode 与配置恢复继承同一模式。
- **按 run_type 消费**：`full`/`script_only` 运行的恢复以 checkpoint 为主（`script_facts` 为 null，不消费剧本事实）；**派生执行事实 checkpoint（R9，P0-4；R10 分阶段冻结，P1-2）**：full 运行不再"剧本生成后一次性冻结全部三项"——`scene_topology` 实际在 `scene_planning` 阶段（`chapter_pipeline.py` 约 112 行 `planner.plan`）才生成，晚于剧本生成与 `voice_binding`（阶段图 `scene_direction → voice_binding → scene_planning → scene_rendering`，§2.12），一次性冻结的时间点不存在；R10 改为**分阶段 append-only checkpoint**，每项在对应阶段**完成后**冻结并带独立 hash：
  - `checkpoint_json.derived_execution_facts.generated_script_facts` + `generated_script_facts_hash`——剧本生成阶段完成后冻结（与 `script_facts` 同构的 `[{segment_key, speaker, text, seq}]`，现状 `background_jobs_scripts.py` 约 440 行写回）；
  - `.voice_resolution` + `voice_resolution_hash`——voice_binding 阶段完成后冻结（剧本生成后实际解析的音色分配，约 494 行导出）；
  - `.scene_topology` + `scene_topology_hash`——scene_planning 阶段完成后冻结（场景拓扑与场景列表，`planner.plan` 产出）；
  - 各子项 hash 独立（**无聚合 `derived_execution_hash` 字段**）；**冻结过的子项不可覆盖（append-only）**。
  恢复规则：**从最后一个完整阶段的下一阶段继续**——已冻结 `generated_script_facts` 则从 voice_binding 继续（音色解析为确定性过程，输入即已冻结剧本事实）；已冻结 `voice_resolution` 则从 scene_planning 继续（拓扑规划为确定性过程，输入即已冻结音色）；已冻结 `scene_topology` 则从 scene_rendering 继续（渲染可重入）；**不重跑已冻结阶段的非确定性剧本生成**，也不读 `ChapterAudio.script_json`/`Project.audio_config` 实时值；**派生事实不参与 `input_signature`**（创建时剧本/音色尚不存在，signed_payload 排除，§2.1 签名注释），由各子项 hash 单独校验并记录到 `result_render_detail`；历史 checkpoint 缺全部子项且失败于剧本生成后阶段的 full 运行**禁止恢复**（回填不可行时按 §2.1 历史运行规则处理）；`audio_from_scripts`/场景重渲染的恢复以快照内嵌的 `script_facts` 正文 + `revision_projection` 重建输入。
- 计费预检（`routes_tasks.py`/`routes_recover.py`/`routes_subtitle.py` 恢复路径）：`resolve_audiobook_billing_pricing_context` 改为以 `run_input_snapshot.billing_context`（含 provider 组合与**不可变 `billing_snapshot` 计价事实**，§2.1）为输入，不再从 `Project.audio_config` 实时解析；冻结与后续结算同样只消费该快照（§8.5）。
- 用户入队后切换引擎或账户层级变化，正在执行/已暂停的任务不受影响：按 A 快照计费、按 A 快照执行。

### 2.12 不同 stage graph 与 progress event

两管线使用不同的 stage graph 和下发给前端的 progress event：

- `legacy_stems`：`[script_analysis, script_adaptation, tts_generation, sound_effects, music, mixing, quality_check]`
- `seed_scene`：`[scene_direction, voice_binding, scene_planning, scene_rendering, l0_quality, omni_review, chapter_assembly]`

前端 `AudiobookProgressStep` 按 `engine_mode` 选择对应的 stage 列表渲染；进行中展示由 `execution_status`（§2.4）驱动，与 `chapter_render_status` 无关。

### 2.13 四个事实源（实施前提）

R8 实施前固定以下事实源，任何组件不得越级读取：

| 范围 | 唯一事实源 | 是否可变 |
|------|-----------|---------|
| 用户当前选择 | `Project.audio_config.audio_engine_mode`（含 auto，展示层归一化） | 可变 |
| 某次生成批次的引擎 | `AudiobookProject.engine_mode` | 不可变（冻结） |
| 某次运行的实际输入 | `ChapterAudioRun.run_input_snapshot`（自包含正文：引擎配置 payload + 剧本事实/原章输入 + 音色解析 + 编辑基线投影 + 运行参数 + 策略与计费含不可变 `billing_snapshot` + input_signature，§2.1 方案 A 按 run_type 合同） | 不可变 |
| 场景编辑历史与当前投影 | `SceneEditRevision` 追加记录及其投影（`SceneEditorDocument`） | 历史不可变；投影按链尾计算 |

### 2.14 场景音频 artifact 登记（试听资产落点）

场景试听不能依赖任务运行目录（`data/audiobook_scene_runs/{task_id}/chapter_{id}/...`，任务结束/目录清理后失效）。

- **登记**：场景渲染完成（含 fallback 产物）后，将场景音频复制到正式 artifact 存储（`backend/data/scene_audio_artifacts/`），并写入 `SceneAudioArtifact` 表：

```python
class SceneAudioArtifact(Base):
    __tablename__ = "scene_audio_artifacts"
    id = Column(Integer, primary_key=True)
    artifact_id = Column(String(64), unique=True, nullable=False)   # uuid/短 ID
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    chapter_audio_id = Column(Integer, ForeignKey("chapter_audios.id"), nullable=False, index=True)  # 发布作用域（R8）
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=False)
    scene_id = Column(String(64), nullable=False)                    # 生成期 scene_id（展示用）
    segment_keys = Column(Text, nullable=True)                       # 稳定锚点（JSON 数组）
    scene_topology_hash = Column(String(64), nullable=False)         # 登记时的拓扑 hash
    content_digest = Column(String(64), nullable=False)              # 文件 sha256
    stored_rel_path = Column(String(500), nullable=False)            # artifact 存储相对路径（非运行目录）
    source_run_path = Column(String(500), nullable=True)             # 原始运行目录路径（审计）
    source_kind = Column(String(32), nullable=False, server_default="seed")  # seed | legacy_fallback | manual
    status = Column(String(16), nullable=False, server_default="staged")    # staged | active | superseded（R7 显式状态机）
    duration_s = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)       # 软删除：superseded 后旧 artifact 保留供审计
    __table_args__ = (
        # 复合外键（R8；R9 收紧为 (run_id, chapter_audio_id)）：run 与 artifact 必须属于同一
        # chapter_audio 运行作用域（依赖 chapter_audio_runs 复合唯一键 (id, chapter_audio_id)，§1.1）
        ForeignKeyConstraint(
            ["run_id", "chapter_audio_id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_scene_audio_artifact_run_scope",
        ),
    )
```

- **落盘约束（2026-10-11 复发事故收口）**：`_build_scene_artifact_entries` 只复制音频后缀的源（`_SCENE_ARTIFACT_AUDIO_SUFFIXES`），非音频源记告警并跳过登记——artifact 文件名后缀直接取自源文件，历史上有测试模块自身被复制成 `art_*.py`，落在数据目录内还会被 pytest 收集、导致 `ROOT_DIR` 推导错位。任务层测试必须用 autouse fixture 把 `_scene_render_mixin.SCENE_ARTIFACT_ROOT` 重定向到 `tmp_path`（`test_audiobook_seed_scene_engine_mixin.py`、`test_audiobook_omni_review_mixin_wiring.py`、`test_audiobook_scene_director_wiring.py` 已加）；守卫与正/反向用例见 `backend/tests/test_scene_artifact_storage_hygiene.py`。
- **普通播放端点**：`GET /audiobook/scenes/{artifact_id}/stream`（权限校验：批次归属 + 章节从属 + `status = 'active'` 且 `deleted_at IS NULL`；短期 `play_token`，复用 `_create_stream_access_token` 模式）；`SceneEditorDocument` 与场景列表返回 `scene_audio_url`（带 token）。
- **审计访问端点**：`GET /audiobook/scenes/{artifact_id}/audit-stream`（仅管理员/项目所有者可访问，不限 `deleted_at` 与 `status`，返回完整 artifact 信息包含 `deleted_at`/`status`）。
- **生命周期（R7 显式状态机，R8 作用域）**：`staged`（渲染完成未发布）→ `active`（发布事务 §2.4 规则 4 g，以 `chapter_audio_id` 为作用域）→ `superseded`（被**同一 chapter_audio 的**新 run 产物替代，同时置 `deleted_at`，物理文件保留 30 天供审计，策略见 §8.3）；staged 与 superseded 均不可经普通端点访问；失败 run 的 artifact 停留在 staged（不激活、不可试听），由 §8 清理策略回收；运行目录按既有任务清理规则删除后试听不受影响。
- **数据库级约束（R8 补全，R9 收紧）**：`status ∈ {staged, active, superseded}` 值域 CHECK；**部分唯一索引** `UNIQUE (run_id, scene_id) WHERE deleted_at IS NULL`（PostgreSQL partial unique index；普通唯一索引在 `deleted_at` 可空时允许多行 NULL，不能防重复登记）；**复合外键 `(run_id, chapter_audio_id) → chapter_audio_runs(id, chapter_audio_id)`（R8 的 `(run_id, audiobook_project_id, chapter_id)` 升级为 R9 运行作用域：run 与 artifact 同属一个 chapter_audio 实例，依赖 §1.1 为 runs 表改复合唯一键）**；`chapter_id` 补充外键到 `chapters.id`；`chapter_audio_id` 外键到 `chapter_audios.id`（发布作用域，§2.4 规则 4 g）。

## 3. 当前实现差距

### 3.1 角色音色绑定全局共享且未覆盖 tts_models 结构

- 存储：`Project.audio_config.characters` 全局一份；实际持久化优先按 `tts_models.{tts_model}.characters` 读写（`project_audio_config.get_characters_for_model`/`set_characters_for_model`），无引擎维度。
- 前端：`frontend/src/pages/audiobook/AudiobookPage.tsx` 的 `characterVoices` 状态为全局一份，切换引擎不切换绑定数据。
- 后果：同一角色名在两引擎下的音色配置互相覆盖；`seed_scene` 依赖的 `reference_source`/`reference_audio_url` 等字段泄露到 `legacy_stems`，反之亦然。

### 3.2 章节状态无引擎维度

- `frontend/src/pages/audiobook/chapterSelectionUtils.ts` 的 `resolveGeneratedChapterIdsFromProjects` 合并所有批次的 `chapter_audios`，无 `engine_mode` 过滤。
- `frontend/src/pages/audiobook/useAudiobookGeneratedChapterIds.ts` 调用 `getAudiobookProjectsByProject` 不带引擎参数，且返回 `Set<number>`（约 61 行），无法表达"可编辑但不可导出""可试听过期""人工评审中"等状态。
- `AudiobookProject` 表无 `engine_mode` 列。

### 3.3 编辑器入口单一

- `frontend/src/pages/AudiobookPage.tsx` `onOpenGeneratedChapter` 恒走 `handleOpenScriptEditor`。
- `frontend/src/pages/audiobook/useAudiobookScriptEditorActions.ts` 通过 `getAudiobookChapterScript` 读取 `ChapterAudio.script_json`（ScriptSegment[] 数组）无场景结构展示。
- 场景级产物（`SceneRenderResult`：scene_id/status/audio_path/quality_report）仅存于 `ChapterAudioRun.checkpoint_json`，无读取与展示接口。

### 3.4 引擎选择位置不合理

- 引擎 ToggleButtonGroup 位于 `frontend/src/pages/audiobook/NarrationAudioConfigPanel.tsx`（第二张卡片），与输出格式、音效配置同卡。
- `frontend/src/pages/audiobook/AudiobookSetupStep.tsx` 中"章节队列"卡片仅包含 `ChapterSelectionPanel`。

### 3.5 生成编排未按引擎分流（分流点不够早）

- `backend/app/services/audiobook/engine_pkg/_generation_mixin.py`（约 114 行）和 `_audio_from_script_mixin.py`（约 80 行）中无论 `engine_mode` 都先执行 `AudioDirector.formulate_strategy()` + `_apply_audio_fx_to_strategy()`，使 `seed_scene` 继承了 `hybrid/audio_drama/audiobook` 风格、`sound_effect_density`/`music_density` 等旧导演行为取向。
- `backend/app/services/audiobook/engine_pkg/_parallel_mixin.py`（约 87 行）的 `prepare_render_assets` 默认 `True`，`seed_scene` 模式仅当调用方显式传 `prepare_render_assets=False` 才跳过素材设计，缺少编排层硬隔离。
- 两引擎共用同一套 stage graph、progress event 和 checkpoint 类型，无法区分场景级状态与分轨级状态。

### 3.6 运行链路实时读取可变配置（无快照闭环）

- `project_audio_runtime.resolve_project_audio_runtime_config`（约 173 行）每次从 `project.audio_config` 实时解析模式、角色绑定与 audio_fx。
- `background_jobs_full.py`（约 50 行）`_apply_project_audio_effects` 直接采用该实时配置；`background_jobs_audio.py`/`background_jobs_scripts.py` 同样。
- `task_support.py`（约 442 行，`_resolve_recover_payload` 类函数）恢复时从 `project` 实时解析运行时配置。
- `routes_recover.py`（约 257 行）、`routes_subtitle.py`（约 173 行）恢复路径的计费预检读取当前项目配置（`resolve_audiobook_billing_pricing_context(project=project, ...)`）。
- `routes_segment_regen.py`（约 341 行）`_resolve_segment_regeneration_runtime_config` 实时解析项目配置。
- `background_jobs_scripts.py`（约 493-508 行）生成完成后把 `voice_manager.export_to_db()` 写回 `audiobook_project.voice_mapping`，与快照不可变冲突。
- 后果：任务入队后用户切换引擎，任务可能按 A 计费、按 B 执行；编辑后重渲染可能拿到旧音色。

### 3.7 API 合约未覆盖引擎分支

- `backend/app/api/v1/projects.py`（约 83 行）`ProjectAudioConfig` Pydantic 模型仅顶层 `characters`/`audio_fx`/`audio_engine_mode`/`seed_audio_model`；GET/PUT 端点（约 449 行）只读写顶层结构。
- `POST /{project_id}/audio-config/auto-voices`（约 562 行）自动分配音色后写顶层，无引擎分支概念。
- `CharacterAudioConfig`（约 45 行）缺少 `reference_source`/`reference_audio_url`/`voice_pool_publication_id` 字段，seed_scene 分支样例依赖的键会被 Pydantic 忽略。
- 按新结构直接提交 `engines` 会被 Pydantic 忽略，运行时无法消费。

### 3.8 回退场景仍返回 success（完成语义矛盾）

- `_scene_render_mixin.py`（约 351 行）对 `legacy_stems` 状态场景生成本地回退素材并继续装配整章；最终（约 525 行）无条件返回 `"success": True`，`scene_metrics["local_fallback_count"]` 已记录回退数量但未影响完成判定。
- 与"全部场景 passed 才算完成"语义冲突，R5 按 §2.4 三维投影状态机修正（R10/P2-1 命名统一）。

### 3.9 场景定位键不稳定且 segment_key 未贯穿

- `scene_engine/planner.py`（约 95 行）scene_id 按 `scene_{number:04d}` 顺序生成；split（约 167 行）派生 `_split_01` 等 ID。
- `ScriptSegment` dataclass（`_dataclasses.py` 约 159 行）无 `segment_key` 字段；script_json 字典层已有 segment_key（`_sanitize_incoming_script_segments` 补齐），进入 Seed 场景规划后丢失。
- 改台词/改说话人/重分场后序号偏移，旧覆盖可能应用到另一段剧情；R5 按 §2.6 稳定锚点 + segment_key 传递链修正。

### 3.10 资源标识与媒体授权

- 仓库存在两个不同 ID：源项目 `project_id` 与生成批次 `audiobook_project_id`。场景编辑接口必须使用 `audiobook_project_id`（与 `routes_script.py` 既有模式一致），并校验章节确属该批次所属源项目。
- `SceneEditorDocument` 不得向前端直接返回本地 `audio_path`（存在本地绝对路径/临时路径泄露与未授权 OSS 地址风险），应返回经权限验证的 `scene_audio_url` 或下载端点。

### 3.11 章节渲染状态无持久化落点

- `ChapterAudio`（`audiobook.py` 约 63 行）无渲染状态字段；`ChapterAudioRun.status`（约 113 行）是任务生命周期状态，不能承载章节聚合状态。
- 批次列表接口（`routes_projects.py` 约 661-727 行）返回 id/status/chapter_audios 摘要，无 `engine_mode` 与渲染状态。
- 前端 `useAudiobookGeneratedChapterIds` 只返回 `Set<number>`，无法区分章节渲染状态（published/desired 三维投影）。

### 3.12 场景试听无资产落点

- 场景文件写在任务运行目录（`_scene_render_mixin.py` 约 168 行 `data/audiobook_scene_runs/{task_id}/...`、约 364 行 fallback 目录）。
- 下载路由只有章节级（`routes_download.py` 约 205 行），无场景级 artifact 授权端点。
- 后果：任务结束或临时目录清理后，场景编辑器试听为空。

## 4. 目标架构

### 4.1 页面布局

```text
┌─ 章节队列（第一卡片）───────────────────────────
│ [分轨合成] [场景生成]   ← 生成引擎切换（顶部） │
│ 已选第 N 章   可生成 X 章   已生成 Y 章      │
│ ┌──────────────────────────────────────────┐  │
│ │ 第1章 · 标题        [状态 Chip]      │  │
│ │ 第2章 · 标题        [状态 Chip]      │  │
│ │ ...                                 │  │
│ └──────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
┌─ 叙事与音频（第二卡片）───────────────────────────┐
│ 输出格式（legacy_stems 时含音效/配乐）    │
└────────────────────────────────────────────────┘
┌─ 角色声音（右侧）────────────────────────────────┐
│ 按当前引擎分支加载/保存绑定             │
└────────────────────────────────────────────────┘
```

### 4.2 章节状态语义

```text
legacy_stems 章节已生成
  = ∃ 批次 B: B.engine_mode == 'legacy_stems'
    ∧ B 下存在该章节的 ChapterAudio（script_json != null && audio_path != null && script_status ∈ {reviewed, approved}）

seed_scene 章节状态（三维投影，§2.4）
  execution_status：queued | running | paused | succeeded | failed | cancelled（任务生命周期，聚合自 ChapterAudioRun.status；数据库值经投影映射——pending/queued→queued、paused/pause_requested→paused、completed→succeeded、canceled/cancelled/expired→cancelled——投影规则与 §1.1 normalize_run_status 同一事实源，此处不复制枚举，§2.4/R16/P1-2）
  published_render_status：rendered_all_seed | rendered_with_fallback | stale | null（持久化于 ChapterAudio.render_status，R11/P2-1 收窄：manual_review_required/failed 为 desired 专属态，发布协议保证不可达、不发布）
  desired_render_status：rendered_all_seed | rendered_with_fallback | manual_review_required | failed | null（最新期望 run 本次结果，§2.4）
  - rendered_all_seed / rendered_with_fallback → 锁定、可导出、计费、收录 generatedChapterIds
  - manual_review_required / failed / stale → 不锁定、不可导出、不收录（由 desired/execution 维度展示）
```

### 4.3 数据流

```text
引擎切换（可变层）
  → 刷新章节状态（engine_mode 过滤的批次查询 + 三维投影状态）
  → 加载对应引擎分支的角色绑定 → characterVoices
  → 加载对应引擎分支的 audio_fx（仅 legacy_stems）或 scene_generation_preferences（seed_scene）
生成任务入队（冻结层）
  → resolve_engine_mode 归一化（auto → 确定值，含旧 seed 键判定）
  → 复用判定：engine_mode + engine_config_fingerprint 一致才复用批次，否则新建
  → 解析当前引擎分支有效配置 → engine_config_snapshot + engine_config_fingerprint 写入批次
  → 创建 ChapterAudioRun：engine_mode_snapshot + run_input_snapshot（完整运行参数 + 事实 hash + revision heads）+ revision_set_hash
  → 后台执行 / 计费预检 / 结算 / 恢复一律读 run_input_snapshot / engine_config_snapshot
点击章节（已生成）
  → 按 §2.5 多批次选择规则定位批次与 engine_mode
  → legacy_stems → 剧本编辑器
  → seed_scene  → 场景编辑器（GET /editor-document + SceneEditorDocument 聚合）
保存场景编辑（seed_scene）
  → 区分编辑类型（dialogue / director_override / voice_binding）
  → 原子事务：FOR UPDATE 锁定 head 行 → 校验 base_revision_hash，不匹配 → 409
  → 创建 SceneEditRevision（append-only，旧 checkpoint 保持只读） + 更新 head 行
  → dialogue 语义变化 → 自动重置 script_status=pending 并清空审定结果
  → 重渲染时：run_input_snapshot = 方案 A 自包含正文（引擎配置 payload + 剧本事实 + 音色解析 + 编辑基线投影 + 运行参数 + 策略与计费），新 ChapterAudioRun
恢复/续跑
  → 只消费 run_input_snapshot（方案 A 自包含正文）恢复，不读取项目当前活跃引擎与实时配置
场景试听
  → 渲染完成登记 SceneAudioArtifact → scene_audio_url（带 play_token）→ 场景编辑器播放
  → 审计端点允许管理员访问已软删除的 artifact
```

### 4.4 生成编排隔离

两套引擎在公共事实层后立即分流（分流点在旧导演策略与并行设计**之前**）：

```text
                          公共入口
                            │
             加载原文 + 角色档案 + 权限
             resolve_engine_mode（auto 归一化）
             创建带 engine_mode + 配置快照的批次
             构造审定 ScriptFacts（含 segment_key）
                            │
            ┌─────────────────┼──────────────────┐
            │                                    │
       legacy_stems                          seed_scene
            │                                    │
   LegacyAudioDirector                    SeedSceneDirector
   (风格/密度策略)                          (场景导演，不运行旧策略)
            │                                    │
   分轨 ScriptSegment 合同               SeedSceneDirection[]
            │                                    │
   逐句音色分配                           VoiceIdentityRegistry
   (VoiceManager)                       + SceneVoiceBindingPlanner
            │                                    │
   TTS 片段生成                          ScenePlanner
   (逐句调用 TTS)                        + ScenePromptCompiler
            │                                    │
   SoundEffectDesigner                   Seed Audio multilingual
   MusicComposer                         逐场景渲染（无分轨素材）
            │                                    │
   Timeline/Mixer                        L0 确定性闸门
   混音装配                               + Omni 影子评审
            │                                    │
   片段/分轨工作台                       SceneAudioAssembler
                                         场景拼接 + 整章时轴 + 字幕
                                         场景音频登记 SceneAudioArtifact
            │                                    │
            └──────── 受控 legacy fallback ────────┘
                  (seed_scene 失败且 terminal policy
                   选择回退时，按失败场景延迟生成)
```

**编排层隔离约束：**

- `seed_scene` 入口在 `AudioDirector.formulate_strategy()` 之前分流，不调用旧导演；不传递 `sound_effect_density`/`music_density` 等旧策略参数到任何下层。
- `seed_scene` 成功路径禁止旧分轨 `Mixer`、`SoundEffectDesigner`、`MusicComposer`、逐句 TTS；允许 `SceneAudioAssembler` 场景拼接（必需环节）。
- `prepare_render_assets` 由管线自身根据 `engine_mode` 决定（`engine_mode == 'seed_scene'` → 恒 False），不依赖调用方传参。
- legacy fallback 是 `seed_scene` 的显式失败动作，按 `FallbackAssetPlan` 按场景延迟生成，不是正常路径预生成。
- 两管线使用不同的 stage graph、progress event 和 checkpoint 类型（§2.12）。

### 4.5 可复用的基础设施

以下能力跨引擎共享（不需隔离）：

- 章节原文和角色档案加载
- `ScriptSegment.text` 和 `speaker` 的审定事实
- 原文保真审计（台词级）
- `VoiceIdentityRegistry` 的合法资产解析
- 通用任务状态、权限和账单基础设施
- `artifact` 存储和 `content_digest`
- ASR provider
- 公共播放器组件
- 发布、暂停、取消和任务跟踪基础设施

## 5. 实施阶段

### 阶段 1：后端数据模型与存储隔离

#### 1.1 Alembic 迁移（`backend/alembic/versions/`）

**发布单元划分（R19/P1-2，Expand/Migrate/Contract——避免把 schema 迁移与运行期编排混入同一个超大迁移）**：本阶段不得实现为单个依赖 Celery 外部状态、需要长停机、无法可靠回滚的超大迁移，拆为三个独立发布单元，每个单元单独写明前置条件、可重复执行规则、数据验证 SQL、失败恢复方式、是否允许旧版本实例继续运行、是否需要维护窗口、下一步准入条件：
- **Expand**：添加可空列、宽 CHECK、新表与兼容读写代码，不收紧任何约束——前置条件：无；可重复执行：`IF NOT EXISTS` 幂等；允许旧版本实例继续运行；无需维护窗口；准入 Migrate 的条件：全部新列/新表建成且兼容读写代码已部署；**并新建迁移进度专用表 `audiobook_canonical_migration_progress`（R20/P2-1；R21/P1-1 补事务边界与失败记录字段，R21/P1-2 补并发认领合同）：`audiobook_project_id`/`chapter_id`/`canonical_chapter_audio_id`/`source_row_ids`(JSON)/`migration_version`/`status`(CHECK ∈ {pending, completed, failed}——本版仅三态，不含 running，R22/P1-1 方案 A)/`completed_at`/`attempts`(Integer 非空 默认 0)/`last_started_at`/`last_failed_at`/`last_error_code`/`failure_detail`，唯一约束 `(migration_version, audiobook_project_id, chapter_id)`。**事务边界（R21/P1-1，修正 R20 “failed 与业务同事务”矛盾——业务事务整体回滚时同事务写入的 failed 标记会一并消失，迁移报告永远看不到失败组）**：只有 `completed` 标记必须与单组数据改指/文件登记/校验在同一事务内写入（事务 A，提交后该组才算可跳过）；`failed` 状态必须在事务 A 回滚后以**独立短事务（事务 B）**写入（upsert `status='failed'` + `failure_detail` + `attempts += 1` + `last_failed_at=now()` + `last_error_code`），失败组不得伪装完成；**事务 B 必须是 fail-closed 条件更新——`INSERT ... ON CONFLICT (migration_version, audiobook_project_id, chapter_id) DO UPDATE SET status='failed', attempts=progress.attempts+1, last_failed_at=now(), last_error_code=EXCLUDED.last_error_code, failure_detail=EXCLUDED.failure_detail WHERE progress.status <> 'completed'`，绝不覆盖已提交的 completed（R22/P1-2）；事务 A 提交结果不确定（客户端断线/驱动异常/连接中断）时不得直接写 failed——先用新连接重读 progress：status=completed 且组级一致性校验通过 → 视为成功，绝不写 failed、绝不递增 attempts；只有确认事务 A 未提交或 progress 仍非 completed 才执行事务 B；attempts 仅在确认失败并写入事务 B 时递增（不确定成功组不得被误计为有失败历史，干扰 Contract 准入与人工排障）**；**`failure_detail` 只记录脱敏后的异常摘要——禁止包含完整堆栈、数据库 DSN、供应商密钥或用户正文**；**重试与不确定结果（R21/P1-1）**：重试不得仅依据调用方本地状态——先读进度表 completed 标记，命中时重跑组级一致性校验（复合外键成立/无重复 active/文件登记齐全）通过后才跳过，覆盖“事务 A 已提交但客户端在收到提交结果前断线”的不确定结果。**并发认领合同（R21/P1-2）**：迁移任务默认**全局单实例**——启动时 `pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)`（会话级，按 migration_version 固定键），获取失败立即退出（不排队、不降级为并行，KISS）；**会话锁连接合同（R22/P1-3）：该会话级锁不随单组事务提交/回滚释放，必须用专用、非池化的 PostgreSQL 连接持有——获取失败立即关闭连接并退出；所有正常完成、异常退出、取消信号路径均在 finally 执行 `pg_advisory_unlock(MIGRATION_VERSION_LOCK_KEY)` 后关闭专用连接；持有全局锁的专用连接不得归还连接池（否则锁随池中连接存活，后续所有迁移实例持续获取失败直到该物理连接被回收）；进程崩溃依赖数据库断连自动释放，启动时记录 run_id/host/pid 供运维诊断；提供运维检查 SQL 定位长期持锁会话（`pg_locks` 按 locktype='advisory' AND objid=MIGRATION_VERSION_LOCK_KEY 过滤 JOIN `pg_stat_activity`），运维人工确认非有效迁移任务后才 `pg_terminate_backend`，禁止自动 kill（存在误杀正在运行迁移的风险）**；组级 advisory lock（③ 方案 A 的 `pg_advisory_xact_lock(hash(audiobook_project_id, chapter_id))`）保留，用于与在线创建路径串行化；每组事务开始时必须：取组级 advisory lock → `SELECT ... FROM audiobook_canonical_migration_progress WHERE (migration_version, audiobook_project_id, chapter_id) FOR UPDATE` → 锁后重查 status：completed 跳过（重跑一致性校验后）、仅 pending/failed 才认领处理——**本版 status 值域恰为 pending/completed/failed（与 CHECK 一致），不存在 running/租约/接管死分支（R22/P1-1 方案 A）**；确需多实例并行时升级为带租约的完整认领状态机（status 扩 running + claim_token/claimed_at/lease_expires_at + CAS 认领与过期 running 接管，同步扩展 CHECK 值域）并在实施文档单列，本版默认不实现；结构化迁移报告从该表派生，单一事实源）。**
- **Migrate**：独立幂等数据迁移任务（非 Alembic 同步事务）——历史回填、canonical 去重合并（见下执行合同）、synthetic run 创建、celery_task_id 回填、历史 ledger 清洗与一致性报告；可重复执行（幂等标记 + 断点续跑，进度持久化至 Expand 创建的 `audiobook_canonical_migration_progress` 表；**全局单实例执行：启动先 `pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)`，获取失败立即退出；会话锁用专用非池化连接持有、finally 解锁并关闭（R22/P1-3）；failed 记录在业务事务回滚后的独立短事务写入（fail-closed 不覆盖 completed，R22/P1-2）；重试先读进度表 completed 并重跑组级一致性校验再跳过，R21/P1-1/P1-2**）；**旧实例策略（R20/P1-3，二选一强制，构成部署准入）**：方案 A（推荐）——Migrate 前完成全量滚动部署，全部存活 API/worker 实例升级至具备重复创建防护的版本并确认旧版本实例数为零；方案 B——Migrate 窗口对 ChapterAudio 创建/恢复/复制入口加写入闸门（允许旧实例读与执行既有 run，但拒绝或排队所有可能新增/恢复 active ChapterAudio 的写操作，闸门日志全程留存）；仅“关闭旧重复创建路径”不足以构成准入——advisory 锁串行化只对运行新代码的实例有效，见 canonical 合同③；大表索引 `CREATE INDEX CONCURRENTLY`（**执行载体约束（R20/P1-2）**：PostgreSQL 不能在事务块内执行 CONCURRENTLY，Alembic 管理须独立 revision + `autocommit_block()` 且不混事务性 DDL，或在 Alembic 事务外专用运维步骤执行，见 canonical 合同⑥）；准入 Contract 的条件：迁移报告全部通过 + 旧 worker/旧批量入队已清空（见下方 cutover 部署步骤）+ **旧版本实例数为零或写入闸门日志证明全程生效（R20/P1-3 门禁证据）**。
- **Contract**：确认旧 worker 已清空后施加 NOT NULL、唯一索引、收窄 CHECK，并删除旧写路径——需要维护窗口（索引/NOT NULL 施加窗口）；回滚方式：`DROP CONSTRAINT`/`DROP INDEX` 恢复宽态（Expand 态兼容读写仍可用）；前置条件：Migrate 报告通过 + 旧批量入队与旧 worker 已下线清空 + **R20/P1-3 门禁证据（旧版本实例数为零或写入闸门日志）**；**施加部分唯一索引前先运行验证 SQL 确认全表无重复 active 组（`SELECT audiobook_project_id, chapter_id FROM chapter_audios WHERE deleted_at IS NULL GROUP BY 1,2 HAVING COUNT(*) > 1` 返回空）；存在历史遗留 INVALID/同名索引时按 canonical 合同⑥ R21/P2-2 身份校验流程处置（校验 schema/表名/`indisvalid`/`indisready`/`pg_get_indexdef` 定义一致后才 DROP，同名不同定义的有效索引停止 Contract）。**

**Alembic 执行边界（R19/P1-2）**：Alembic 迁移只做数据库 schema 变更与数据回填——**不得直接操作 broker、执行 Celery revoke、drain/cancel 任务或部署代码**；cutover 五步中的“④部署新版本”“⑤drain/cancel 旧活动任务”与 CHECK 两阶段收窄的“部署新代码/drain”均为**独立部署步骤**（部署系统/运维流程负责，各有准入与验证），与 schema 迁移分属不同发布步骤，实施文档必须分开排期。

- `AudiobookProject`：新增 `engine_mode` 列（可空）→ 历史行按 §2.1 引擎推断回填 → 置 `NOT NULL` + `server_default='legacy_stems'` → CHECK 约束（`engine_mode IN ('legacy_stems','seed_scene')`）→ `(project_id, engine_mode, deleted_at)` 组合索引；新增 `engine_config_snapshot`（Text，可空）、`engine_config_fingerprint`（String(64)，可空，index）与 `snapshot_status`（String(20)，**无 server_default（R19/P2-1）——迁移顺序：新增可空列（nullable、无默认）→ 按证据回填快照与 status → 校验不存在非法组合（frozen 无快照/legacy_unfrozen 有快照）→ 置 NOT NULL + 三态 CHECK；新记录由应用服务在创建批次时显式写 `snapshot_status`（不依赖数据库默认——保留 `server_default='frozen'` 会使历史行与绕过应用服务的插入在无快照时被误标 frozen，违反后续 CHECK 或产生错误语义），并确认所有旧写路径已改造为显式写入**）。
- **历史快照回填**：迁移脚本遍历历史批次，先按 §2.1 四项证据推断引擎并判定证据等级；**只有批次级 checkpoint/运行参数/billing 事实能证明输入**的批次才从可验证来源解析写入 `engine_config_snapshot`（`snapshot_status='frozen'`）；引擎证据不足、只能从当前可变配置推导的批次写入推导快照并标记 `snapshot_status='legacy_unverified'`（**禁止恢复**）；解析失败置 `snapshot_status='legacy_unfrozen'`（禁止恢复）。同时计算 `engine_config_fingerprint`（业务标识字段含 `seed_audio_model` 与 `providers` 组合参与 hash）。
- `ChapterAudio`：新增 `render_status`（String(32)，可空，仅 seed_scene 使用）、`render_status_detail`（JSON，可空）、双指针列 `desired_run_id`/`published_run_id`（Integer，可空，**复合外键 `(desired_run_id, id) → chapter_audio_runs(id, chapter_audio_id)` / `(published_run_id, id) → chapter_audio_runs(id, chapter_audio_id)` ON DELETE RESTRICT/NO ACTION——R10/P1-1：普通复合 FK 的 SET NULL 作用于两个引用列（含非空主键 `id`），删除被引用 run 时 PostgreSQL 因主键 NOT NULL 直接失败；**R11/P2-2 归因修正**：RESTRICT 只能保证"被 `desired_run_id`/`published_run_id` 当前引用的 run 行不可物理删除"——未被任何指针引用、且无 output/ledger 关联的 cancelled/superseded 终态 run 在数据库层仍可删；若契约是"任何 run 只墓碑化、永不物理删除"（终态 run 保留供审计/账单/回填引用，物理文件按 §8 清理，行不删），该强制策略必须落在 **repository/service 层**：所有删除 run 的入口改为置 `deleted_at` 墓碑（或直接禁止删除），并**清除一切 `DELETE FROM chapter_audio_runs` 物理删除路径**，不能归因于双指针 FK；R8 单列外键升级（R9/P0-3），指针不可能跨章节/跨实例**）、`published_input_signature`（String(64)，可空，§2.4 双指针发布模型）、**`published_provenance`（String(20)，可空：`published` | `legacy_unverified`，§2.4，R9/P1-1；R10 进入 API schema，P1-1）**与来源审计引用 `source_audiobook_project_id`/`source_chapter_audio_id`（Integer，可空）、**`source_script_hash`（String(64)，可空）、`source_script_review_version`（String(64)，可空）、`source_provenance_json`（JSON，可空）——§2.1 复制合同持久化落点（R7）**；**`script_review_version`（String(64)，可空——dialogue 审批的审核版本，§2.9 审批闭环，R8）**；**唯一 active 约束（R10/P0-4，R11 canonical 去重升级，P1-5）**：迁移第一步**canonical 去重合并**——每个 `(audiobook_project_id, chapter_id)` 组内先按 **canonical 优先级**选出保留行：①**有效已发布产物**（`audio_path` 非空且对应 run 终态/published 输出登记存在）→ ②**approved script + 审核证据**（`script_status='approved'` 且 `script_review_json`/`script_review_version` 非空）→ ③完整字段数（非空列最多）→ ④最近更新时间 → ⑤`id` 最大；其余行**合并迁移到 canonical 行**（该组全部 runs 的 `chapter_audio_id` 改指 canonical 行、`chapter_audio_outputs` 一并迁移、canonical 缺失的剧本/审核证据从持有行复制、音频/字幕物理文件保留并登记到 canonical 行）→ **一致性校验通过后**才软删除（置 `deleted_at`，物理文件按 §8 清理——**迁移代码不得调用 `repository.soft_delete_older_duplicates` 约 638 行起的 `unlink` 物理删除逻辑**，R11/P1-5：较老记录可能持有有效 audio_path/字幕/approved script/审核证据，按"保留 id 最大"去重会丢失真正有效的历史产物），随后建**部分唯一索引 `UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL`**（数据库层约束替代现状 `repository.soft_delete_older_duplicates` 约 613 行的应用层兜底）；**并发插入 loser（R10/P0-4）**：首事务插入成功后另一事务捕获 `IntegrityError` → 按 §2.9 SAVEPOINT 协议 `nested.rollback()` 后重读该行（不抛 `InFailedSqlTransaction`）复用；**软删除恢复冲突行为（R10/P0-4）**：恢复被软删除的 `ChapterAudio`（置 `deleted_at = NULL`）时若同 `(audiobook_project_id, chapter_id)` 已存在 active 行 → 唯一索引冲突，返回 `409`，提示先清理/重建，不允许产生两条 active；**历史产物回填（R9/P1-1，R10 明确落点，P1-1）**：迁移对有 `audio_path` 的历史章节，找最新 `status='completed'` 且 `run_type ∈ {full, audio_from_scripts, chapter_remix}` 的 run 回填 `published_run_id` + 一条 `status='published'` 的 `ChapterAudioOutput` + **`published_provenance='legacy_unverified'`**（可导出但**不作为 CAS 发布基线**）；**无法确认 run 归属的历史产物（R10/P1-1）**：复合外键禁止指向不存在的 run，不能"声称无法确认又建立强归属"——统一落点为**创建 synthetic migration run**：每个无法归属的历史章节创建一条 `run_type='migration_placeholder'`、`status='completed'`、`dispatch_status='cancelled'`、`chapter_audio_id` 指向该章节 active `ChapterAudio`、`run_input_snapshot=null` 的合成 run（**不可恢复、不可结算、不可重试、不可派发**），`published_run_id` 指向它——双指针模型、复合外键与 published 部分唯一索引全部保持成立；seed_scene 历史产物 **`render_status` 不再回填精确 `rendered_all_seed`**（无法验证当时是否全 Seed 成功），保持 `null` + `published_provenance='legacy_unverified'`——API 消费者按 `published_provenance` 显式渲染"历史产物（未验证）"，**不允许把未知 fallback/manual 历史误读为全 Seed 成功**（§2.4/§3.3）。**canonical 合并迁移执行合同（R19/P1-3，生产可执行性）**：上述合并规模大、跨 chapter_audios/runs/outputs 多表与物理文件，必须满足以下合同方可上生产：①**分批短事务**——按 `(audiobook_project_id, chapter_id)` 逐组处理，**每组一个独立短事务**（单事务只处理一组，禁止跨组大事务），单组事务目标时长 ≤ 秒级，避免长时间锁定 chapter_audios/runs/outputs；②**幂等标记与断点续跑（R20/P2-1 持久化合同；R21/P1-1 事务边界修正）**——**事务 A（组处理事务）**：锁定/认领组 → canonical 选择 → runs/outputs 改指 → 文件登记 → 组级一致性校验 → 进度表写 `status='completed'`（含 canonical 选择证据）→ 单次 commit，**仅 completed 标记与业务数据同事务——事务提交后该组才算可跳过**（进度不同事务会导致重跑重复合并或数据回滚后错误跳过）；**事务 A 失败整体回滚（组回到待处理状态），随后以事务 B（失败记录事务，独立短事务）**upsert 进度表 `status='failed'` + `failure_detail`（**脱敏后的异常摘要——禁止包含完整堆栈、数据库 DSN、供应商密钥或用户正文**）+ `attempts += 1` + `last_failed_at=now()` + `last_error_code`，失败组不得伪装为完成；**事务 B 必须 fail-closed 条件更新：`INSERT ... ON CONFLICT (migration_version, audiobook_project_id, chapter_id) DO UPDATE SET status='failed', attempts=progress.attempts+1, last_failed_at=now(), last_error_code=EXCLUDED.last_error_code, failure_detail=EXCLUDED.failure_detail WHERE progress.status <> 'completed'`——绝不把已提交的 completed 覆盖为 failed（否则已合并组会被重复处理：重复 synthetic run/重复输出登记/错误二次改指，R22/P1-2）；**不确定结果处理**：事务 A 发生提交结果不确定错误（客户端断线/驱动异常/连接中断）时，先用新连接重读 progress——status=completed 且组级一致性校验通过则视为成功，绝不写 failed；只有确认事务 A 未提交或 progress 仍非 completed 才执行事务 B；**attempts 仅在确认失败并写入事务 B 时递增，不确定成功组不得递增（否则迁移报告把成功组误统计为有失败历史，干扰 Contract 准入与人工排障，R22/P1-2）**；**重试与不确定结果**：重试不得仅依据调用方本地状态——先读进度表 completed 标记，命中时重跑组级一致性校验（复合外键成立/无重复 active/文件登记齐全）通过后才跳过，覆盖“事务 A 已提交但客户端在收到提交结果前断线”的不确定结果；重跑时跳过已完成组，中断后从首个未完成组继续；③**防迁移期间新增重复 active 行（R20/P1-3 版本门禁）**——advisory 锁串行化只对运行新代码的实例有效，旧版本实例不取新锁仍可全程写入重复 active 行，故必须二选一构成部署准入：**方案 A（推荐）**——Migrate 前完成全量滚动部署，全部存活 API/worker 实例升级至具备重复创建防护的版本，确认旧版本实例数为零；创建/恢复/复制路径统一取 `pg_advisory_xact_lock(hash(audiobook_project_id, chapter_id))` 与合并事务串行化；**方案 B**——方案 A 不可行时，Migrate 窗口对 ChapterAudio 创建/恢复/复制入口加写入闸门（拒绝或排队所有可能新增/恢复 active 行的写操作，允许旧实例读与执行既有 run，闸门日志全程留存）；仅“部署关闭旧重复创建路径（`soft_delete_older_duplicates` 应用层兜底与绕过唯一索引的创建入口）”不足以构成准入；**并发认领合同（R21/P1-2，KISS 默认）**：迁移任务默认全局单实例执行——启动时 `pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)`（会话级，按 migration_version 固定键），获取失败立即退出（不排队、不降级为并行）；**会话锁用专用非池化连接持有、finally 解锁并关闭、不归还连接池（R22/P1-3，完整合同见 Expand 进度表）**；无论单实例与否，每组事务开始必须：取 project/chapter 组级 advisory lock → `SELECT ... FROM audiobook_canonical_migration_progress FOR UPDATE` → 锁后重查 status：completed 跳过（重跑组级一致性校验后）、仅 pending/failed 才认领处理——**本版 status 值域仅 pending/completed/failed（与 CHECK 一致），不存在 running/租约/接管死分支（R22/P1-1 方案 A）**——组级锁同时承担与在线创建路径（方案 A advisory 锁）的串行化；确需多实例并行时升级为带租约的完整认领状态机（status 扩 running + claim_token/claimed_at/lease_expires_at + CAS 认领与过期 running 接管，同步扩展 CHECK 值域）并在实施文档单列，本版默认不实现；④**失败恢复**——事务 A 任一步失败整体回滚（文件登记与数据库写入同事务，不出现“已登记未改指”分裂），该组回到待处理状态；**失败记录不在事务 A 内写（会随回滚消失）——由回滚后的独立短事务 B 写 failed/failure_detail/attempts/last_failed_at/last_error_code（见②，R21/P1-1）**，该组由断点续跑重试，连续失败组进入迁移报告人工处理；⑤**物理文件只登记不搬动**——合并只把既有物理文件登记到 canonical 行（runs/outputs 改指 + 字段复制），**不在迁移内搬动或删除任何物理文件**（清理按 §8 保留期策略独立执行）；⑥**索引创建（R20/P1-2 执行载体）**——部分唯一索引与新增大表索引在**全部重复 active 行清理完成后**创建：`CREATE INDEX CONCURRENTLY`（不阻塞写入；**PostgreSQL 不能在事务块内执行 CONCURRENTLY——普通 Alembic revision 默认运行在事务中，不能直接替代常规 `op.create_index()`：必须在 Alembic 事务外的专用运维步骤执行，或在 Alembic 独立 revision 中使用 `with op.get_context().autocommit_block():` 且不与其他事务性 DDL 混在同一 revision；创建前先运行验证 SQL 确认全表无重复 active 组（见 Contract 前置条件）；创建后验证 `pg_index.indisvalid = true`；失败留下 INVALID 索引需先 DROP 再重建——**DROP 前必须校验索引身份（R21/P2-2）：索引所属 schema、所属表、索引名、`indisvalid = false`、`indisready` 状态与 `pg_get_indexdef` 定义与目标定义一致全部匹配才执行 `DROP INDEX CONCURRENTLY schema.index_name`（DROP INDEX CONCURRENTLY 同样不能在普通事务块内执行）；若发现同名但定义不同的有效索引，停止 Contract 转人工处置，不得自动删除**；维护窗口可接受写入阻塞时也可选阻塞式 `CREATE UNIQUE INDEX`（更简单可靠，需写明取舍）**）；⑦**半迁移状态读取（R20/P1-2 修正；R21/P1-1 跳过判定）**——迁移期间旧服务读到未处理组时按现状多 active 行语义运行（读兼容，Expand 态不收紧），已处理组在 Migrate 期间由③的应用层写闸门/advisory 锁保护，而非唯一索引——全局部分唯一索引只能在全部重复 active 行清理完成后创建，Contract 之前不保护任何组（R19 原文“已处理组立即受唯一索引保护”不成立）；**已处理组的跳过判定以进度表 completed 为准并重跑组级一致性校验（不依赖调用方本地状态，覆盖事务 A 提交后断线的不确定结果，R21/P1-1）**；⑧**结构化迁移报告**——输出每组 canonical 选择依据、合并行数、失败组清单与一致性校验结果（无重复 active、复合外键成立、物理文件登记齐全），报告通过是 Contract 单元施加部分唯一索引的准入条件（§6 验收 61 / §7 测试）；**报告从 `audiobook_canonical_migration_progress` 表派生（单一事实源，R20/P2-1），不另维护第二份进度来源；失败组清单含 `attempts`/`last_error_code`/脱敏 `failure_detail`（R21/P1-1）**。
- `ChapterAudioRun`：新增 `engine_mode_snapshot`（String(20)，回填自批次 engine_mode）、**`chapter_audio_id`（Integer，不可变，外键 → `chapter_audios.id`——首次运行在入队事务内创建/锁定 `ChapterAudio` 后写入，R9/P0-3）**、`run_input_snapshot`（Text，可空；方案 A 自包含正文，§2.1 **按 run_type 合同**）、`revision_set_hash`（String(64)，可空）、`input_signature`（String(64)，可空）、**`dispatch_status`（String(16)，非空，server_default='pending'，值域 CHECK `{pending, dispatched, cancelled, unknown}`——R10/P0-1 可靠派发状态机，§2.1 六步第 4 步；synthetic migration run 置 `cancelled`）**、**`celery_task_id`（String(128)，最终态非空 + 唯一索引——创建 run 时预生成的固定 task id，派发意图与 Celery 消息一一对应，R11/P0-1；R12/P0-2：现状列可空且历史批量入队共用同一 task id（`task_support.py` 约 760/762 行单 uuid4 传给全部 run），直接加 `NOT NULL` + `UNIQUE` 会失败——按本行末尾 cutover 五步回填后再施加约束）**、**`predecessor_run_id`（Integer，可空，外键 → chapter_audio_runs.id——创建 run 时持久化的上一 desired run id（非动态推断），派发失败条件补偿的前提，R11/P1-4）**、**`dispatch_attempts`（Integer，非空，server_default=0——dispatcher 重试计数，超过上限（如 5 次）转 unknown 人工对账，R11/P0-1）**、**`next_dispatch_at`（DateTime(timezone=True)，可空——dispatcher 下次可认领时间，创建时 now()，R11/P0-1）**、**`dispatch_claim_token`（String(64)，可空）/`dispatch_claimed_at`（DateTime(timezone=True)，可空）——dispatcher 认领租约（R11/P0-1）**、**`dispatched_at`（DateTime(timezone=True)，可空——`apply_async` 成功（`dispatch_status='dispatched'`）时写，dispatcher"已投递未认领超时重投"判定基准，R12/P1-5）**、**`claim_token`（String(64)，可空）/`claimed_at`（DateTime(timezone=True)，可空）/`lease_expires_at`（DateTime(timezone=True)，可空）——worker 消费租约（R11/P1-1：CAS 认领写入、heartbeat 续期、过期接管；R12/P0-1 拆分首认领与过期接管两条 CAS）**、**`result_render_status`（String(32)，可空：本次运行结果状态，运行结束（无论是否发布）时写入，§2.4 三维投影；值域按引擎：seed_scene ∈ {rendered_all_seed, rendered_with_fallback, manual_review_required, failed}、legacy_stems 系 ∈ {completed, failed}，R9/P0-2）与 `result_render_detail`（JSON，可空，R8）**；**复合唯一键 `(id, chapter_audio_id)`（R8 的 `(id, audiobook_project_id, chapter_id)` 升级为 R9 运行作用域，供 `scene_audio_artifacts`/`chapter_audio_outputs` 复合外键与 `ChapterAudio` 双指针复合外键引用，§2.4/§2.14）**；**历史 `chapter_audio_id` 确定性回填算法（R10/P1-1）**：迁移在部分唯一索引建成后执行——按 `(audiobook_project_id, chapter_id)` 匹配，先为每个历史章节确保存在唯一 active `ChapterAudio`（不存在则创建），再将该章节全部历史 `ChapterAudioRun.chapter_audio_id` 回填为该行 id（确定性算法，不允许留空；回填后校验复合唯一键 `(id, chapter_audio_id)` 无冲突），最后执行上述历史产物回填与 synthetic migration run 创建。**run 墓碑化与级联删除（R12/P1-4，审计保留优先）**：新增 `deleted_at`（DateTime(timezone=True)，可空，index）——"任何 run 只墓碑化、永不物理删除"契约的落点；现有 `audiobook_project_id`/`chapter_id` 外键 `ON DELETE CASCADE`（`audiobook.py` 约 121/127 行）与 `chapter_audio_outputs`（约 1045/1046 行）/`scene_audio_artifacts` 的 run/chapter_audio 外键 CASCADE **全部改为 `ON DELETE RESTRICT/NO ACTION`**——否则即使 repository 不再显式删除 run，父项目/章节的硬删除仍会级联物理删除 run 与关联输出；`AudiobookProject` 删除只允许软删除（置 `deleted_at`，项目已有该列），章节硬删除前需先解除 run 引用或并入项目软删除路径处理。**celery_task_id cutover（R12/P0-2，独立迁移步骤，顺序执行）**：①**分类历史 run**——按终态（succeeded/failed/cancelled/completed）/非终态（pending/queued/running）/dispatch 挂起（`dispatch_status='unknown'`）分类；②**parent/child 回填**——旧批量任务（一个 `AudiobookTask.celery_task_id` 对应多条 run）保留 `AudiobookTask` 为父任务，为同批次每个 run 生成唯一 legacy 派发 id（`legacy-{task_id}-{run_id}`）**仅回填 `run.celery_task_id`**（子派发表不保存该列，R14/P1-a 单一事实源；`legacy-` 前缀标识，**不做 broker 关联**——仅审计用）；③**null 且无父任务的 run** 回填仅审计用唯一 id（`legacy-run-{run_id}`）；④**部署“禁止旧批量入队”的版本（独立部署步骤，非 Alembic，R19/P1-2）**——新代码强制每 run 预生成唯一固定 id（`task_support.py` 约 760-779 行批量签名改为逐 run 独立任务，旧批量入队路径下线）；⑤**等待或取消全部旧非终态任务（drain/cancel，独立部署/运维步骤，非 Alembic——Alembic 不得直接操作 broker 或执行 Celery revoke，R19/P1-2**，避免旧 worker 继续按共享 task id 回写 run 状态）——**全部完成上述步骤后才施加 `NOT NULL` + `UNIQUE` 约束（Contract 单元）**；灰度期间新旧状态查询/暂停/恢复/SSE 对 `legacy-` 前缀 run 走展示投影（按子派发表定位，不按 broker task id 关联）；验收用"多 run 共用旧 Celery ID + null ID + 旧活动任务"三类数据做真实 PostgreSQL 迁移（§6 验收 66）。**run 状态值域 CHECK（R14/P1-c fail-closed 前置②，R15/P0-1 补 `expired`）**：`status` 加 CHECK 约束 `IN ('pending','queued','running','paused','pause_requested','completed','failed','canceled','cancelled','expired')`——**`expired` 是现有合法数据库状态**：候选片段被新候选顶替（`segment_candidate_registry.py` 约 152 行 `run.status = "expired"`）与临时片段过期清理（`temp_segment_janitor.py` 约 149 行）都会写入，且 worker 活动检查（`background_jobs_shared.py` 约 128 行 cancelled/canceled/expired 集合）依赖该值——遗漏 `expired` 会让上述现有路径在迁移后报 CHECK 约束错误，**迁移前清洗存量不能解决未来继续写入**；**先按父任务聚合规则 fail-closed 前置①清洗历史非值域状态再施加**（无法归一的置 `failed` 并记录审计错误；**`completed` 是合法数据库态保持不变，仅查询投影映射 `succeeded`**，清洗不得改写为投影值），保证新写入不再产生聚合查询的未知值。**run 计费封口与计费账户（R17/P0 + R17/P1-3）**：新增 `billing_finalized_at`（DateTime(timezone=True)，可空——计费封口时点，finalizer 置位后该 run 禁止任何新 ledger 创建/供应商调用/二次结算，一次性置位不可回退，§2.1 六步第 6 步/§8.5）；新增 `billing_account_user_id`（Integer，可空，不可变——**创建 run 时从冻结事务的目标账户写入（与冻结同一事务），是计费账户唯一权威来源，运行期不随 `Project.user_id` 变化（R17/P1-3）**；迁移回填：历史 run 从 `run_input_snapshot.billing_context.billing_account_user_id`（若已含）或匹配的 active freeze 事件（`admin_operation_logs` 中 `POINTS_BILLING_FREEZE` 且 `request_params->>'billing_key'` 等于该 run billing key 的记录，取 `resource_id`）确定性回填，回填失败仍为 NULL 的历史 run 禁止人工收敛与结算（收敛入口 409/422 提示先修复计费账户字段，finalizer 拒绝结算）；新 run 创建后非空（冻结成功才入队，冻结账户即 `billing_account_user_id`）。**不可变数据库约束（R18/P2）**：迁移回填完成后施加 BEFORE UPDATE trigger `trg_chapter_audio_runs_billing_immutable`——拒绝非空后修改/清空 `billing_finalized_at`（一次性置位不可回退）与非空后修改 `billing_account_user_id`（允许 NULL → 值的回填，覆盖迁移回填与首次写入场景）；repository 层同样不得提供这两列的 update 入口（R17 仅应用层承诺“不可变”，R18 以数据库约束 + 测试锁定保障）。

- `AudiobookTask`：`status` 列从 `String(20)` 扩展为 `String(32)`（容纳父聚合值 `completed_with_partial_failure`），加 CHECK 约束。**CHECK 两阶段收窄上线（R14/P1-b，避免迁移后旧代码写暂停态触发 CHECK 失败）**：现状 API 直接写父任务 `pause_requested`（`routes_tasks.py` 约 86 行 `task.status = PAUSE_REQUESTED_STATUS`）、旧 worker 直接写父任务 `paused`（`job_tracker.py` 约 395 行）——若阶段 1.1 直接施加仅含聚合值域的 CHECK，迁移后旧 API/旧 worker/灰度实例一写暂停态即被数据库拒绝，现有暂停路径整体破坏。**第一步（迁移期，新旧约束并存）**：CHECK 接受旧值域 ∪ 新聚合值域 ∪ 暂停态：`status IN ('pending','running','completed','failed','cancelled','completed_with_partial_failure','pause_requested','paused')`（`completed_with_partial_failure` 为新聚合值，旧代码不会写；`pause_requested`/`paused` 为过渡期放行，收窄后移除）；**第二步（收窄期，依次完成全部前置后才执行）**：①部署"暂停只写 run、父任务只写聚合值"的代码（§1.3/§1.5 路由与 worker 改造——暂停态下沉到 run，父任务保持聚合 `running`）→ ②drain/cancel 所有仍可能写旧父状态的 worker（旧批量任务等待完成或取消，避免旧 worker 继续按共享 task id 回写父表状态）→ ③清洗父表遗留暂停态并重新聚合（存量 `pause_requested`/`paused` 父任务按 run 状态重算聚合值，`pause_requested`/`paused` 不再出现在父表）→ ④最后收窄 CHECK 移除 `pause_requested`/`paused`，仅保留聚合值域 `IN ('pending','running','completed','failed','cancelled','completed_with_partial_failure')`——**严禁"先迁移后部署"的直接收窄顺序**。父聚合前必须先做 `normalize_run_status()` SQL CASE 投影（参见父任务聚合规则 R13/P0-a、R14/P1-c）。

- 新表：
  - `scene_edit_revisions`（§2.9 双表设计，含 `revision_hash` 全表唯一约束、**复合唯一键 `(id, project, chapter, edit_type)` 与自引用复合外键（parent 作用域，R7）**）；
  - `scene_edit_revision_heads`（每 (project, chapter, edit_type) 唯一行，**仅存 `head_revision_id`**，hash 经 JOIN 获得，**复合外键约束 head 作用域（R7）**）；
  - `scene_audio_artifacts`（§2.14 结构，含 `source_kind`、`chapter_id` 外键到 `chapters.id`、**`chapter_audio_id` 外键到 `chapter_audios.id`（R8 发布作用域）**、**`status` 列（staged/active/superseded，R7）值域 CHECK、复合外键 `(run_id, chapter_audio_id) → chapter_audio_runs` 复合唯一键（R8，R9 收紧为运行作用域）**、**部分唯一索引 `UNIQUE (run_id, scene_id) WHERE deleted_at IS NULL`**）；
  - **`ledger_reconciliation_audits`（R15/P1-4 人工收敛审计；R16/P2-1 完整约束模型，append-only）**——人工对账转态的唯一审计落点（写路径见 §1.1 记录规则"manual_reconciliation 人工收敛写路径"）：

```python
class LedgerReconciliationAudit(Base):
    __tablename__ = "ledger_reconciliation_audits"
    id = Column(Integer, primary_key=True)                              # 显式主键（R16/P2-1）
    ledger_id = Column(Integer, ForeignKey("billing_usage_ledger.id", ondelete="RESTRICT"), nullable=False, index=True)  # 被收敛 ledger；RESTRICT 防 ledger 删除后审计悬空（R16/P2-1）
    from_status = Column(String(32), nullable=False, server_default="manual_reconciliation")  # 恒为 manual_reconciliation（CHECK 固定）
    to_status = Column(String(32), nullable=False)                      # succeeded | confirmed_failed（CHECK 限制）
    operator_user_id = Column(Integer, nullable=False)                  # 操作管理员（R16/P2-1 非空）
    operator_username = Column(String(64), nullable=False)              # 操作人展示名快照（R16/P2-1 非空）
    reason = Column(Text, nullable=False)                               # 人工对账原因（必填）
    evidence = Column(JSON, nullable=False)                             # 供应商查询结果、回执等证据（必填）
    confirmed_quantity = Column(Numeric(20, 6), nullable=True)          # 人工确认的用量事实快照（R16/P0：succeeded 必填且 > 0；confirmed_failed 为 NULL）
    previous_provider_request_id = Column(String(64), nullable=True)    # 收敛前原供应商请求 ID（结构化证据，R17/P1-1：不依赖自由结构 evidence）
    new_provider_request_id = Column(String(64), nullable=True)         # 收敛后供应商请求 ID（仅 NULL 补齐，已有值时不变，R17/P1-1）
    previous_commit_stage = Column(String(16), nullable=True)           # 收敛前 commit_stage（pre_call|post_call|result_persisted，R17/P1-1）
    new_commit_stage = Column(String(16), nullable=True)                # 收敛后 commit_stage（单调推进，禁止 result_persisted 倒退，R17/P1-1）
    recovery_method = Column(String(16), nullable=False, server_default="manual")  # 恢复方式：当前恒为 manual（R17/P1-1）
    reconciled_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())  # 数据库端默认 now()，带时区（R16/P2-1）
    __table_args__ = (
        CheckConstraint("from_status = 'manual_reconciliation'", name="ck_ledger_reconciliation_audits_from"),
        CheckConstraint("to_status IN ('succeeded','confirmed_failed')", name="ck_ledger_reconciliation_audits_to"),
        # 用量事实一致性（R16/P0）：to succeeded 时 confirmed_quantity 必填且 > 0；confirmed_failed 时不带用量
        CheckConstraint("to_status <> 'succeeded' OR (confirmed_quantity IS NOT NULL AND confirmed_quantity > 0)",
                        name="ck_ledger_reconciliation_audits_quantity"),
        CheckConstraint("to_status <> 'confirmed_failed' OR confirmed_quantity IS NULL",
                        name="ck_ledger_reconciliation_audits_quantity_null"),
        # 结构化证据一致性（R17/P1-1；R18/P1-1 单调性改 rank 编码）：succeeded 收敛 commit_stage 单调不减、前后阶段必须在值域内
        CheckConstraint("previous_commit_stage IS NULL OR previous_commit_stage IN ('pre_call','post_call','result_persisted')",
                        name="ck_ledger_reconciliation_audits_prev_stage"),
        CheckConstraint("new_commit_stage IS NULL OR new_commit_stage IN ('pre_call','post_call','result_persisted')",
                        name="ck_ledger_reconciliation_audits_new_stage"),
        # 单调性编码为 pre_call=1 < post_call=2 < result_persisted=3 的 rank 比较（R18/P1-1）：R17 CHECK 硬编码 succeeded 时
        # new_commit_stage='post_call'，与“原记录已 result_persisted 收敛保持不变（new_commit_stage='result_persisted'）”语义冲突
        # （验收 80 的断言一跑就撞 CHECK），必须改为 new ≥ prev
        CheckConstraint("to_status <> 'succeeded' OR (new_commit_stage IS NOT NULL AND previous_commit_stage IS NOT NULL AND CASE new_commit_stage WHEN 'pre_call' THEN 1 WHEN 'post_call' THEN 2 ELSE 3 END >= CASE previous_commit_stage WHEN 'pre_call' THEN 1 WHEN 'post_call' THEN 2 ELSE 3 END)",
                        name="ck_ledger_reconciliation_audits_stage_monotonic"),
        CheckConstraint("recovery_method IN ('manual')", name="ck_ledger_reconciliation_audits_recovery"),
    )
```
**append-only 合同（R16/P2-1；R19/P2-2 升级为数据库级强制保护）**：审计记录只可插入——repository/service 层不提供该表的 update/delete 入口（仅 insert + 只读查询），不存在 `UPDATE ledger_reconciliation_audits`/`DELETE FROM ledger_reconciliation_audits` 任何代码路径。**仅服务层无入口不足以支撑“不可变审计”表述（R19/P2-2：无法防止新增代码直接调 SQLAlchemy session 修改、管理脚本执行 UPDATE/DELETE、后续误加 repository 更新方法、数据库账户本身拥有表更新权限）**——必须叠加数据库级保护（两者二选一，推荐 trigger）：①BEFORE UPDATE OR DELETE trigger `trg_ledger_reconciliation_audits_append_only` → `RAISE EXCEPTION`（与 `scene_edit_revisions` append-only 先例及 R18/P2 计费不可变 trigger 一致）；或对应用数据库角色仅授予该表 SELECT/INSERT 并撤销 UPDATE/DELETE。测试必须直接执行 SQL 验证数据库拒绝修改与删除（不只是验证当前 service 无入口，§6 验收 82 / §7 测试）。
  - **`chapter_audio_outputs`（R8 完整模型，§2.4 规则 3/4：run 级输出登记表）**：

```python
class ChapterAudioOutput(Base):
    __tablename__ = "chapter_audio_outputs"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id", ondelete="RESTRICT"), nullable=False, unique=True)  # 每 run 至多一条（R13/P1-c: RESTRICT 替代 CASCADE，与迁移合同一致）
    chapter_audio_id = Column(Integer, ForeignKey("chapter_audios.id", ondelete="RESTRICT"), nullable=False, index=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    status = Column(String(16), nullable=False, server_default="staged")   # staged | published | superseded
    file_status = Column(String(16), nullable=False, server_default="present")  # present | purged | missing（R9/P2-3 墓碑）
    purged_at = Column(DateTime(timezone=True), nullable=True)             # 物理文件清理时间（登记与摘要保留）
    audio_path = Column(String(500), nullable=False)                       # run 级路径
    duration = Column(Float, nullable=True)
    file_size = Column(Integer, nullable=True)
    subtitle_path = Column(String(500), nullable=True)
    subtitle_format = Column(String(16), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('staged','published','superseded')", name="ck_chapter_audio_output_status"),
        CheckConstraint("file_status IN ('present','purged','missing')", name="ck_chapter_audio_output_file_status"),
        # published 时整章可导出字段必须齐全
        CheckConstraint("status <> 'published' OR (audio_path IS NOT NULL AND duration IS NOT NULL AND file_size IS NOT NULL)",
                        name="ck_chapter_audio_output_published_fields"),
        # 每个 chapter_audio_id 至多一条 published（部分唯一索引）
        Index("uq_chapter_audio_output_published", "chapter_audio_id", unique=True,
              postgresql_where=text("status = 'published'")),
        # run 与输出必须属于同一运行作用域（复合外键 → chapter_audio_runs 复合唯一键 (id, chapter_audio_id)，R9/P0-3）
        ForeignKeyConstraint(
            ["run_id", "chapter_audio_id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_chapter_audio_output_run_scope",
        ),
    )
```
- **`audiobook_task_dispatches`（R11/P0-3 任务-派发数据合同；R12/P1-1 降级为"父子关系 + 展示投影"，单一事实源为 `ChapterAudioRun`）**：父 `AudiobookTask` 保持现状（唯一 `celery_task_id` 列仍存在，作为父任务占位），每 run 一条子派发记录——**不复制 run 的派发/租约/进度/错误字段**（R11 版的 `status`/`worker_id`/`claim_token`/`claimed_at`/`lease_expires_at`/`attempts`/`last_error` 全部删除，杜绝双写不一致源；展示所需字段经 JOIN run 获得，R12/P1-1）：

```python
class AudiobookTaskDispatch(Base):
    __tablename__ = "audiobook_task_dispatches"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("audiobook_tasks.id"), nullable=False, index=True)      # 父任务
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=False, unique=True)  # 每 run 至多一条派发
    chapter_audio_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        # 复合外键：保证子派发的 chapter_audio_id 必须属于该 run（R12/P1-1）
        ForeignKeyConstraint(
            ["run_id", "chapter_audio_id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_audiobook_task_dispatch_run_scope",
        ),
    )
```

**父任务聚合规则（R13/P0-a 修正 R12/P1-1 值域歧义）**：聚合输入为 run 状态（经子派发 JOIN `ChapterAudioRun` 获得），**必须先做 SQL CASE 投影将数据库原始值归一化为规范化值**，再基于规范化值做互斥矩阵判定。`normalize_run_status()` 投影映射如下：

```sql
CASE
  WHEN run.status IN ('pending','queued') THEN 'queued'
  WHEN run.status = 'running' THEN 'running'
  WHEN run.status = 'paused' THEN 'paused'
  WHEN run.status = 'pause_requested' THEN 'pause_requested'
  WHEN run.status = 'completed' THEN 'succeeded'
  WHEN run.status = 'expired' THEN 'cancelled'    -- R15/P0-1：expired 是合法数据库态（候选 supersede/临时片段过期清理，§1.1 run CHECK），归一化为非结果终态与 cancelled 同组；原始值保留在聚合审计 detail_json
  WHEN run.status = 'failed' THEN 'failed'
  WHEN run.status IN ('canceled','cancelled') THEN 'cancelled'
  ELSE 'unknown'
END AS normalized_status
```

**fail-closed 前置条件（R14/P1-c）**：`normalize_run_status` 必须对**合法状态全集**有映射（上表已含 `pause_requested`——R13 版缺失该分支导致合法 `pause_requested` run 落入 `ELSE 'unknown'`，而矩阵②把它视为进行中，聚合结果悬空）；同时对**真正未知的值**明确 fail-closed，不静默输出无法消费的字符串：①**实施前清洗全部历史状态**——迁移脚本扫描 `chapter_audio_runs.status` 非值域值，逐一按可验证证据归一化（`canceled`→`cancelled` 统一拼写；`pause_requested`/`paused`/`expired` 保留——`expired` 是现有合法数据库状态，见 §1.1 迁移清单 run CHECK 与写路径，R15/P0-1）；**历史数据库态 `completed` 保持不变、绝不改写为 `succeeded`**（`succeeded` 是 API 规范化投影值而非数据库状态，且不在 run CHECK 值域内——若迁移脚本照抄"`completed`→`succeeded`"清洗，清洗结果自身无法通过约束；`completed`→`succeeded` 只发生在查询投影 `normalize_run_status`，R15/P0-1）；无法归一的置 `failed` 并记录审计错误，**不完成清洗不得部署聚合查询**；②**run 状态增加数据库 CHECK**（值域 `pending/queued/running/paused/pause_requested/completed/failed/canceled/cancelled/expired`，§1.1 迁移清单）——新写入不再产生未知值；③聚合查询遇 `unknown` 时写审计错误（父任务 `error_message`/`detail_json` 记 `aggregation_unknown_status` + 具体 run 列表）；④父任务投影为 `failed`（或专门人工干预状态）而非无分支返回——矩阵加 unknown 兜底分支（见下）。

**父任务互斥矩阵（基于规范化值 `normalized_status` 的计数穷尽规则，R17/P1-2；同一时刻只命中一条，不并列；优先级自上而下，R15/P1-1 把 unknown 置顶于一切业务分支之前）**：规则按计数表述而非谓词组合，保证规范化值域全部组合均有定义——R17/P1-2 修复 {cancelled, failed} 无结果缺陷（旧第③条“任一 cancelled 且其余全部终态”对 {cancelled, failed} 前置成立但既非全部 cancelled 也无成功项、第④条带“否则”不继续，该组合悬空）：
① 任一 `unknown`（含 NULL 与非值域历史值）→ **fail-closed**：父任务投影 `failed`，`error_message`/`detail_json` 记录审计错误 `aggregation_unknown_status`（列出全部 unknown 的 run 及原始值），**禁止无分支返回/静默丢弃**（R14/P1-c；**最高优先级**——若排在终态组合之后，`{failed, unknown}` 会先命中终态分支错误产出 `completed_with_partial_failure`，与“任一 unknown 都 fail-closed”声明矛盾，R15/P1-1）；
② 任一 `running`/`queued`/`pause_requested`/`paused` → 父 `running`（进行中优先，等待全部终态；不要求其余全终态——任何进行中即 running）；
③ 全部 `succeeded`（succeeded 数 = run 总数且 > 0）→ `completed`；
④ 全部 `cancelled`（cancelled 数 = run 总数且 > 0，含 `expired` 归一化，R15/P0-1）→ `cancelled`；
⑤ 至少一个 `succeeded` 且存在 `failed`/`cancelled`（无进行中、无 unknown）→ `completed_with_partial_failure`（覆盖 {succeeded, cancelled}、{succeeded, failed}、{succeeded, failed, cancelled}）；
⑥ 无 `succeeded` 且至少一个 `failed`（其余为 cancelled 或空）→ `failed`（覆盖 {failed}、{cancelled, failed}——R17/P1-2 补定义的组合）。
run 总数为 0（无子派发）不适用本矩阵（父任务保持原状态，不投影结果）。
进度 = Σ run.progress 加权（按 run 数）。**run 状态机含 `pause_requested` 过渡态**。**job_id 语义（R13/P1-a 命名空间字符串）**：`job_id` = **`task:{AudiobookTask.id}`**（与 §2.1 第 4 步一致）；**暂停/恢复/取消按 run 级操作**：`routes_tasks.py` 按 `audiobook_task_dispatches.run_id` 定位子派发（`celery_task_id` 查询兼容保留），父任务聚合下发；**SSE 按 run 发出**（事件携带 `run_id` + `job_id` = `task:{id}`）；**`GET /tasks/{task_id}/status` 优先按 `task:{id}` 解析返回父聚合视图**（含 children 摘要），单 run 时退化为原语义。**前端 `StageStatus` 同步（R13/P0-a，R15/P1-3 补齐穷举映射）**：`types.ts` 联合类型新增 `'cancelled'` 和 `'completed_with_partial_failure'`；`coerceStageStatus`（`utils.ts` 约 79 行）识别新值，未知值不再无条件降级 `'pending'`（改为保留原值或 `'unknown'`）。**新增联合类型键必须同步补齐全部 `Record<StageStatus, ...>` 穷举映射，否则 tsc 编译立即报错（缺少属性）**：①`constants.ts` 约 56 行 `STAGE_STATUS_LABELS: Record<StageStatus, string>` 新增两键文案（如 `cancelled: '已取消'`、`completed_with_partial_failure: '部分完成'`）；②`TaskStageDetails.tsx` 约 23 行 `STAGE_STATUS_COLORS: Record<StageStatus, {bg;border;text}>` 新增两键；③`audiobookTheme.ts` 约 83 行 `taskStatus` 颜色角色新增 `cancelled`/`completed_with_partial_failure`（复用现有颜色 token 组合，如 danger/warning 系），映射键与类型键一一对应；④前端测试断言两映射完备且新状态渲染不崩。**语义边界（R15/P1-3）**：`completed_with_partial_failure` 本质是父任务聚合状态而非单阶段状态——本阶段共用 `StageStatus` 时父任务视图渲染该值即可；更清晰的做法是拆分 `TaskLifecycleStatus`（父任务）与 `StageStatus`（单阶段）两个类型，记录为后续可选重构，本阶段不引入以控制改动范围。

- **`provider_dispatch_capabilities`（R11/P1-3 供应商派发能力声明）**：每 provider 一行声明四项能力（对齐 `provider_recovery.py` 约 17 行 `RECOVERY_METHODS = ("request_query","temporary_url")` 的既有恢复方法）：`accepts_idempotency_key`（bool：是否接受外部幂等键）、`returns_request_id`（bool：是否返回供应商 request ID）、`supports_request_query`（bool：是否支持按 request ID 查询结果）、`has_recoverable_result_url`（bool：是否有可恢复的临时结果 URL）；声明缺失/未知按"不支持"处理。**恢复语义（R11/P1-3，R12 按实际证据决策，P1-3）**：能力表是**可变配置**，不能以"当前能力"重新解释历史调用——恢复决策依据**本次调用时持久化的实际证据**（`billing_usage_ledger` 证据字段，见下）：①已持有 `provider_request_id` → 按 request query 查询结果（provider 声明 `supports_request_query` 且调用时已获得该 ID）；②已持有 `result_url` 且 `result_url_persisted_at` 非空 → 按临时 URL 拉取；③`idempotency_key_sent=true` 且调用时能力快照声明 `accepts_idempotency_key`（provider 确认接受该键）→ 可安全重放（不产生第二笔费用）；④仅"provider 声明支持"但本次调用**未实际获得任何证据**（进程在收到 request ID 前崩溃、URL 未落库）→ 不得自动重放，转 `manual_reconciliation` 人工对账（对齐 `provider_recovery.py` 约 19-26 行 `RECOVERY_STATUSES` 的 confirmed_failed/manual_review 先例）。**既不支持外部幂等又无法查询的供应商**，在"外部成功、本地未落账"窗口后只能转 `manual_reconciliation` 人工对账，**不得自动重新调用并承诺"不产生第二笔费用"**（R10 该承诺只对支持幂等/可查询的供应商成立）。

- **`billing_usage_ledger`（R9/P1-3 用量事实源，R10 状态机 P1-3；R11 四态，P1-2）**：

```python
class BillingUsageLedger(Base):
    __tablename__ = "billing_usage_ledger"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, server_default="pending")  # pending | succeeded | confirmed_failed | manual_reconciliation（R10/P1-3；R11/P1-2 四态；R14/P0：manual_reconciliation 长 21 字符，String(16) 会被 PostgreSQL 拒绝——扩至 String(32)）
    attempt_key = Column(String(64), nullable=False)        # 内部幂等键（对齐 provider_recovery.internal_attempt_key：generation_input_hash:attempt_number）
    provider = Column(String(32), nullable=False)          # seed_provider | asr_provider | fallback_tts ...
    pricing_key = Column(String(64), nullable=True)         # billing_snapshot 计价键——用量维度键（seed_scene/tts/asr/remix，与 billing_snapshot.prices 顶层键一一对应，R18/P1-3；非 provider+model 组合——provider/model 位于 prices[pricing_key] 值结构内部），结算据此匹配价格快照中的单价（R10/P1-3）；pending 时未知可空，succeeded 时必须非空（R17/P1-4 CHECK）
    provider_request_id = Column(String(64), nullable=True)   # 供应商原始请求 ID（R13/P0-b 统一命名；可空；供应商不返回时用 attempt_key 承担幂等）
    encrypted_result_url = Column(Text, nullable=True)        # 加密临时结果 URL（供恢复拉取，R13/P0-b）
    result_url_expires_at = Column(DateTime(timezone=True), nullable=True)  # encrypted_result_url 到期时间（R13/P0-b）
    usage_kind = Column(String(32), nullable=False)        # seed_render | tts_chars | asr_seconds | remix（值域 CHECK）
    quantity = Column(Numeric(20, 6), nullable=True)        # 实际用量（pending 时未知为空，succeeded 时必须 > 0）
    unit = Column(String(16), nullable=False)              # 计量单位（second | char，与 billing_snapshot.prices[*].unit 同值域同语义，值域 CHECK，R17/P1-4 补 CHECK；R19/P1-1：值域来自唯一单位常量表）
    billing_snapshot_id = Column(String(64), nullable=True)  # 关联该 run 的不可变 billing_snapshot；succeeded 时必须非空（R17/P1-4 CHECK）
    idempotency_key_sent = Column(Boolean, nullable=False, server_default="false")  # 本次调用实际向 provider 传递外部幂等键（R12/P1-3）
    recovery_method = Column(String(32), nullable=True)    # 本次调用实际采用的恢复方法：request_query | temporary_url | replay | manual（R12/P1-3）
    result_url_persisted_at = Column(DateTime(timezone=True), nullable=True)  # 临时结果 URL 落库时间
    capability_snapshot_json = Column(JSON, nullable=True)    # 调用时 provider_dispatch_capabilities 完整能力快照（不可变 JSON，替代仅版本号，R13/P0-b）
    commit_stage = Column(String(16), nullable=False, server_default="pre_call")  # pre_call | post_call | result_persisted（R12/P1-3 提交阶段）
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        # 内部去重：同 run 同 attempt_key 只记一条（调用前写 pending，重试幂等）
        UniqueConstraint("run_id", "attempt_key", name="uq_billing_usage_ledger_attempt"),
        # 供应商侧去重：同 run 同 provider 同 request 同 usage_kind 只记一次（succeeded 后防重复入账）；
        # R11/P1-2 改部分唯一索引：provider_request_id 可空（NULL 不参与去重——供应商不返回 request id 时由 (run_id, attempt_key) 唯一约束承担去重）；
        # R14/P0：索引列与条件统一为 provider_request_id（引用不存在的 request_id 会在 SQLAlchemy 建表元数据解析或 Alembic 迁移阶段失败）
        Index("uq_billing_usage_ledger_dedup", "run_id", "provider", "provider_request_id", "usage_kind", unique=True,
              postgresql_where=text("provider_request_id IS NOT NULL")),
        CheckConstraint("status IN ('pending','succeeded','confirmed_failed','manual_reconciliation')", name="ck_billing_usage_ledger_status"),
        CheckConstraint("usage_kind IN ('seed_render','tts_chars','asr_seconds','remix')", name="ck_billing_usage_ledger_usage_kind"),
        # succeeded 必须可结算：实际用量 + 有效计价键 + 有效快照引用（R16/P0 加 quantity；R17/P1-4 加 pricing_key/billing_snapshot_id——
        # 缺定价键或快照的 succeeded 记录无法计算金额却会被 strict barrier 放行，自动路径与人工收敛必须同过可定价性校验）
        CheckConstraint("status <> 'succeeded' OR (quantity IS NOT NULL AND quantity > 0 AND pricing_key IS NOT NULL AND billing_snapshot_id IS NOT NULL)",
                        name="ck_billing_usage_ledger_succeeded_fields"),
        # 计量单位值域（R17/P1-4；R19/P1-1：与 billing_snapshot.prices[*].unit 同为计量单位 second|char——币种由价格字段名表达，
        # unit 不再承担价格表达单位；值域常量与 usage_kind → pricing_key → unit 映射为唯一常量表，快照生成/transition service/人工收敛/测试共用）
        CheckConstraint("unit IN ('second','char')", name="ck_billing_usage_ledger_unit"),
        # 提交阶段值域（R12/P1-3）
        CheckConstraint("commit_stage IN ('pre_call','post_call','result_persisted')",
                        name="ck_billing_usage_ledger_commit_stage"),
    )
```

> 记录规则（R10/P1-3 状态机，对齐 `provider_recovery.py` 约 83 行既有 attempt 语义；R11/P1-2 四态扩展，P1-3 provider 能力约束；R12/P1-2 结算封口，P1-3 证据字段）：**供应商调用前**以稳定 `attempt_key` 写 `status='pending'` 记录（quantity 未知为空），同时持久化**调用证据**：`idempotency_key_sent`（本次是否实际向 provider 传递外部幂等键）、`capability_snapshot_json`（调用时 `provider_dispatch_capabilities` 完整能力快照，R13/P0-b）、`commit_stage='pre_call'`；向支持幂等的 provider 传递该 key（或等价的供应商幂等键，能力声明见上）；**成功返回后**经**统一 ledger transition service**（R17/P1-4：worker 自动路径与人工收敛共用同一转态服务，禁止各自直接 UPDATE）执行可定价性校验——`pricing_key` 存在于该 run `billing_snapshot.prices`、`unit` 与 `prices[pricing_key].unit` 一致（同为计量单位 second|char，R19/P1-1）、`billing_snapshot_id` 指向有效快照、`quantity > 0`——校验通过则同一条记录转 `status='succeeded'` 并补填 `quantity`/`provider_request_id`（provider_request_id 可空，非空时由部分唯一索引去重）、`commit_stage='post_call'`；**校验失败（定价键/快照缺失或不匹配）不得转 succeeded，转 `status='manual_reconciliation'` 人工对账**（R17/P1-4：不允许产生“终态但缺定价事实”的 succeeded 记录——历史不可验证记录显式进入人工对账而非 NULL 静默放行）；**结果 URL 落库后**写 `result_url_persisted_at` 并置 `commit_stage='result_persisted'`；**确定失败**（供应商明确报错/补偿已释放）→ 转 `status='confirmed_failed'`（不结算、不再重放）；**无法判定**（外部成功与否不明）→ 转 `status='manual_reconciliation'`（不自动结算，人工对账后转 succeeded 或 confirmed_failed）；恢复续跑命中 `(run_id, attempt_key)` 唯一约束幂等（不重复写、不覆盖 pending）；供应商不返回 provider_request_id 时以 `attempt_key` 承担幂等与去重（succeeded 不再要求 provider_request_id 非空，非空时由部分唯一索引去重）；**恢复决策按实际证据（R12/P1-3，R13/P0-b 证据字段落地）**：恢复时按该记录持久化的 `provider_request_id`/`encrypted_result_url` + `result_url_expires_at`/`idempotency_key_sent` + `capability_snapshot_json` 决定查询/拉取/重放/人工对账——**不得用当前能力表配置重新解释历史调用**（仅"支持声明"而无实际证据的调用不自动重放）；结算以 `status='succeeded'` 记录汇总 × `billing_snapshot` 计价事实为准，`pricing_key` 匹配正确单价（§8.5）；`segment_candidate` 不写；进程在"供应商成功、本地未落账"窗口崩溃 → 恢复后 pending 记录仍在（调用前已写），**按证据**（provider 能力声明 + 本次实际证据）查询或重放结果补录 succeeded——**用量不丢失、不产生第二笔费用**；既不支持外部幂等又无法查询的 provider 只能转 `manual_reconciliation` 人工对账，**不得自动重新调用并承诺不重复收费**（R11/P1-3 修正 R10 无条件承诺）；**取消/失败按证据关账（R18/P0）**：写 run `cancelled`/`failed` 必须同事务关账本 run 全部 `status='pending'` ledger——无供应商证据（`commit_stage='pre_call'` 且 `provider_request_id IS NULL` 且 `idempotency_key_sent = false`）→ `confirmed_failed`；已发出或结果不明 → `manual_reconciliation`（零二次调用）；不得残留 pending（否则 barrier 永远过不了、冻结挂死，见 §2.1 执行终态写协议）。**结算封口（R13/P1-b strict barrier，替代 R12/P1-2 supplement；R14/P1-e 补幂等键数据合同；R17/P0 升级为 run 计费封口）**：strict barrier 只校验“该 run **已有** ledger 全部终态（`succeeded`/`confirmed_failed`）且无未收敛 `manual_reconciliation`”，**不足以阻止结算后新产生用量**——worker 的 ledger 写入路径不持账户锁（仅 run 行锁），收敛事务“barrier 通过 → settle 提交”后 worker 仍可为下一阶段新建 `pending` ledger 并转 `succeeded`，新增费用无法补扣（禁止 supplement、唯一索引阻止二次 settle），形成永久少扣费（R17/P0）。**最终结算因此只能由统一 finalizer 执行**：前置条件 = run 已进入不可继续调用供应商的执行终态（`completed`/`failed`/`cancelled`/`expired`）+ 无有效 worker lease（`lease_expires_at IS NULL` 或 `< now()`——**执行终态 CAS 同步清租约（R18/P0），或租约自然过期**）+ 全部 ledger 已终态 + `billing_finalized_at IS NULL`；单事务顺序：`pg_advisory_xact_lock(billing_account_user_id)`（账户锁，R17/P1-3）→ `SELECT ... FROM chapter_audio_runs WHERE id = :run_id FOR UPDATE`（run 行锁——finalizer 与 worker 新建 ledger 的共同串行化点；后续如需锁既有 ledger 行统一按 `ledger.id` 升序，§2.9 三层锁序 + 锁内写入顺序合同，R20/P1-1，R21/P2-1）→ 校验前置条件 → 置 `billing_finalized_at = now()`（一次性置位不可回退，§2.1 六步第 6 步）→ strict barrier → 执行唯一最终 settle（一次性普通 settle，不引入“补充结算”——不存在原 settle 事件需要“补充”）→ **单次 commit**；`record_points_billing_settle` 约 474 行的“已 settle 短路”在此语义下不再构成障碍：未被最终 settle 时不会发生短路，最终 settle 后短路防止重复。禁止走 `provisional settlement` + `supplement` 两条路径——未收敛时保留冻结，收敛后一次性结算。**任何路径不得绕过 finalizer 直接 settle**（worker 完成/失败落库、人工收敛、dispatcher 补偿均只把 run 推进终态或收敛 ledger，settle 一律由 finalizer 在 run 行锁内完成）。**settle 幂等数据合同（R14/P1-e，替代 R13 仅字符串声明）**：选"billing_key 即幂等域"方案（最简单，不加列）——**幂等域 = `billing_key = audiobook:{audiobook_project_id}:run:{run_id}` 本身**（已 run 级唯一），复合串 `{billing_key}:settle:{run_id}` 中的 `:settle:{run_id}` 后缀为冗余（billing_key 已含 run_id）：**①不得把复合串作为新 billing_key 传入 `record_points_billing_settle`**（`_filter_logs_by_billing_key`（约 197 行）按 `request_params.billing_key` 精确匹配，会查不到原 billing_key 下的 active freeze，`_resolve_active_freeze_log`（约 477 行）返回 None → `require_active_freeze=True` 时结算被拒绝）；**②复合串仅写入 `request_params.settle_scope` 作审计描述，不承担幂等**（request_params 是 JSON，无唯一约束，写进去不构成幂等保证）；**③幂等落点三层**：a. **账户级串行化**——最终 settle 在共享 points mutation service 的账户 advisory 锁内执行（§2.9/§8.5，`pg_advisory_xact_lock(user_id)`），两个并发 settle 事务串行，后到者在锁内重查事件流看到先到者的 settle → 短路；b. **锁内应用层短路**——`record_points_billing_settle` 现有"最新事件为 settle 即返回 None"（约 474 行 `_latest_event_kind(...) == POINTS_BILLING_EVENT_KIND_SETTLE`）**必须运行在账户锁内**（现状调用点无锁，锁由共享 service 改造提供，R12/P0-3）；c. **数据库层兜底（新增，R15/P0-2 修正索引作用域与历史清洗）**——`admin_operation_logs` 建部分唯一索引：`UNIQUE (resource_id, (request_params->>'billing_key')) WHERE operation_type = 'POINTS_BILLING_SETTLE' AND COALESCE(request_params->>'dedupe_superseded', 'false') <> 'true'`（PostgreSQL expression 部分唯一索引；`request_params->>'billing_key'` 为 NULL 时唯一比较不生效，天然兼容无 key 的手工事件）——数据库层保证同账户同 billing_key 至多一条 settle 事件，即使绕过应用层短路也写不进去。**索引作用域必须用 `resource_id` 而非 `user_id`（R15/P0-2）**：`AdminOperationLog.user_id` 的模型语义是"操作用户 ID"（`admin_log.py` 约 17 行 comment），实际被扣费账户存放在 `resource_id = target_user_id`（`user_center_points_events.py` 约 288-293 行写日志时 `user_id=actor_user_id`、`resource_id=target_user_id`）——按 `user_id` 建索引会允许**不同操作者对同一目标账户和同一 billing_key 各写一条 settle**；当前有声书自动结算恰好 actor==target，但共享 points mutation service 的数据库不变量**不得依赖这一偶然调用方式**。**历史重复 settle 清洗必须让被取代行退出索引谓词（R15/P0-2）**：仅给 JSON 加普通审计标记不够——旧重复行的 operation_type 与 billing_key 不变时仍全部满足索引谓词，`CREATE UNIQUE INDEX` 依旧因重复键失败；迁移时对同一 billing_key 的重复 settle 组**保留最新一条（不置位），其余写 `request_params.dedupe_superseded = true`**（显式被谓词 `<> 'true'` 排除；备选方案为改归档 operation_type 如 `POINTS_BILLING_SETTLE_SUPERSEDED`，二选一——推荐 dedupe_superseded 标记，保留 operation_type 审计语义）；**事件流聚合必须忽略被标记行**：余额/冻结重算与"已 settle"短路检查（`_list_billing_logs_for_key`/`_latest_event_kind` 等）过滤 `request_params.dedupe_superseded = true`，否则索引虽建成、历史重复扣减仍进入余额计算。**④并发 settle 验收**：两个并发最终 settle 事务（真实 PostgreSQL）断言只产生一条 settle 事件、一次积分扣减（§6 验收 / §7 测试）。**manual_reconciliation 人工收敛写路径（R15/P1-4，计费审计路径，禁止直接改库）**：人工对账转态必须经专用审计入口，不允许直接 UPDATE 数据库：①**入口与权限**——管理员专用 `POST /admin/billing/ledger/{ledger_id}/reconcile`（仅管理员角色，非管理员 403），请求体为按目标状态区分的联合类型（R16/P0）：`target_status='succeeded'` → 必填 `quantity`（Numeric，人工确认实际用量，> 0）+ `reason` + `evidence`，可选补充 `provider_request_id`（**仅允许从 NULL 补齐：原记录已有值时新值必须为空或与现值一致，否则 409/422——不得覆盖原始供应商证据，R17/P1-1**）与 `pricing_key`/`billing_snapshot_id`（**仅允许 NULL 补齐，用于历史迁移转来的人工记录补全定价事实，提供时必须通过快照匹配校验否则 422，R17/P1-4**），`commit_stage` 单调推进（**仅 `pre_call` → `post_call`；原记录已为 `post_call`/`result_persisted` 时保持不变，禁止倒退丢失“结果已落库”阶段语义，R17/P1-1**）——数据库 CHECK `ck_billing_usage_ledger_succeeded_fields` 强制 `status='succeeded' → quantity IS NOT NULL AND quantity > 0 AND pricing_key IS NOT NULL AND billing_snapshot_id IS NOT NULL`（R17/P1-4 收紧），而 manual_reconciliation 正是"供应商是否成功、实际用量是否已落库尚不明确"的状态（quantity 完全可能为空，pending 起即未知），仅转状态不补用量会直接触发 CHECK 失败；`target_status='confirmed_failed'` → 必填 `reason`/`evidence`，不要求 quantity、不得把未经确认的用量带入结算（quantity 不更新；confirmed_failed 不参与结算，结算只统计 succeeded，§8.5）。**收敛前快照校验（R16/P0）**——目标 succeeded 前校验原 ledger 的 `usage_kind`/`unit`/`pricing_key` 能与该 run 的不可变 `billing_snapshot`（`billing_snapshot_id` 关联）匹配（计价键存在、单位一致、可定价），不匹配拒绝收敛（422 并返回差异），防止产生无法定价或按错误价格结算的 succeeded 记录；**计费账户一致性校验（R17/P1-3）**——账户锁键取自该 ledger 所属 run 的不可变 `billing_account_user_id`（**禁止从当前 `Project.user_id` 推导**——冻结事实在 `AdminOperationLog.resource_id`，项目归属变化后按当前所有者会锁错账户、找不到原 active freeze、甚至对错误账户写 settle），同时强制校验该 run 的 active freeze（`POINTS_BILLING_FREEZE` 未释放）的 `resource_id == billing_account_user_id` 且 `request_params->>'billing_key'` 等于该 run 的 billing key（run_id 一致性由 billing_key 蕴含），任一不匹配拒绝收敛（409/422）；`billing_account_user_id IS NULL`（历史回填失败）的 run 拒绝收敛（409 提示先修复计费账户字段）；②**不可变审计记录（R16/P2-1 完整约束模型，§1.1 迁移清单；R17/P1-1 加结构化证据字段）**——新表 `ledger_reconciliation_audits`：显式主键/`ledger_id` NOT NULL + ON DELETE RESTRICT/`from_status` CHECK 恒 `manual_reconciliation`/`to_status` CHECK ∈ {succeeded, confirmed_failed}/`operator_user_id`/`operator_username`/`reason`（Text 必填）/`evidence`（JSON：供应商查询结果、回执等，**自由结构只存原始回执，证据事实以结构化字段为准，R17/P1-1**）/`confirmed_quantity`（本次人工确认的用量事实快照：succeeded 必填且 > 0、confirmed_failed 为 NULL）/`previous_provider_request_id`/`new_provider_request_id`/`previous_commit_stage`/`new_commit_stage`（**结构化记录原/新供应商证据与提交阶段，R17/P1-1**；值域 CHECK + succeeded 单调不减 CHECK（**rank 编码 pre_call=1 < post_call=2 < result_persisted=3，new ≥ prev——R18/P1-1 修正 R17 硬编码 post_call 撞 result_persisted 收敛语义**）与 `previous_commit_stage` 非空）/`recovery_method`（当前恒 `manual`，CHECK）/`reconciled_at`（数据库端 now() 默认带时区）；append-only：repository/service 层无该表 update/delete 入口；③**单事务原子收敛（R16/P1-1 替代"CAS 先提交、settle 后执行"两段式；R17/P0 加 run 行锁与 finalizer 联动）**——账户锁、run 行锁、快照校验、ledger CAS、审计、barrier、finalizer 全部放入同一个数据库事务，顺序固定：`pg_advisory_xact_lock(run.billing_account_user_id)`（账户锁，与冻结/结算同一锁键，§2.9；来源见 R17/P1-3）→ `SELECT ... FROM chapter_audio_runs WHERE id = :run_id FOR UPDATE`（run 行锁，R17/P0——与 worker 新建 ledger 的串行化点；**R20/P1-1 禁止式：收敛入口必须按 ledger_id 以不加锁的普通 SELECT 解析所属 run 与计费账户，任何实现禁止在账户锁与 run 行锁之前按 ledger_id 查询或 FOR UPDATE ledger——先锁 ledger 再取账户锁会与 worker 终态关账（账户+run 锁 → 等 ledger 锁）构成死锁环，完整三层锁序见 §2.9——**R21/P2-3 预读使用限制：该无锁预读结果仅用于确定锁键与路由，禁止用于任何安全判断（ledger 当前状态/quantity/provider_request_id 是否为空/run 是否终态/是否允许 finalizer/previous/new 审计字段生成一律不得使用预读值）；取锁后必须重新读取并逐项校验——ledger.id 仍存在、`ledger.run_id` 与预读一致、`run.billing_account_user_id` 与预读锁键一致、`ledger.status='manual_reconciliation'`、`run.billing_finalized_at IS NULL`（任一不一致 → 409/422 拒绝）；`ledger.run_id` 不可变性落为数据库约束（BEFORE UPDATE trigger）或 repository 禁止更新入口，防止未来修复脚本/迁移改 run_id 后锁住错误账户****）→ 读取并校验 ledger/run/billing snapshot（含上述用量/计价/计费账户一致性校验与 `status='manual_reconciliation'` 前置）→ **CAS 更新 ledger 及用量事实（证据单调，R17/P1-1）**：`UPDATE billing_usage_ledger SET status = :target, quantity = CASE WHEN :target = 'succeeded' THEN :quantity ELSE quantity END, provider_request_id = CASE WHEN provider_request_id IS NULL THEN :provider_request_id ELSE provider_request_id END, pricing_key = CASE WHEN pricing_key IS NULL THEN :pricing_key ELSE pricing_key END, billing_snapshot_id = CASE WHEN billing_snapshot_id IS NULL THEN :billing_snapshot_id ELSE billing_snapshot_id END, commit_stage = CASE WHEN :target = 'succeeded' AND commit_stage = 'pre_call' THEN 'post_call' ELSE commit_stage END, recovery_method = 'manual' WHERE id = :ledger_id AND status = 'manual_reconciliation'`（rowcount=0 → 已被其他管理员处理或状态已变，返回 409，防重复操作与并发双处理；**CAS 同时更新 status/quantity/provider_request_id/commit_stage/recovery_method，不是只更新状态；provider_request_id/commit_stage 只单调推进、不覆盖既有证据**——原 `provider_request_id` 已有值时管理员传入不同 ID 由请求校验先行拦截 409/422，`result_persisted` 不倒退）→ 写 reconciliation audit（与 CAS 同一事务，**结构化记录原/新 `provider_request_id` 与 `commit_stage` + `recovery_method='manual'`，R17/P1-1**，任一步失败整体回滚，不产生"审计已记、状态未转"或"状态已转、无审计"的分裂）→ **strict barrier**（该 run 全部 ledger 终态检查，本事务内刚更新的行立即可见）→ **finalizer 联动（R17/P0；R18/P0 触发路径）**：**run 已进入执行终态（completed/failed/cancelled/expired）且无有效 worker lease（`lease_expires_at IS NULL` 或 `< now()`）且 barrier 通过 → 同一事务内置 `billing_finalized_at = now()` 并执行唯一最终 settle**（幂等域 = run 级 billing_key，三层落点见上，锁内短路 + 部分唯一索引兜底）；**run 未终态 → 只提交 ledger 与审计、不 settle、不置封口**，等 run 真正结束后由统一 finalizer 结算（run 后续阶段产生的新 ledger 会纳入该次结算，杜绝"settle 在先、ledger 在后"的永久少扣费）→ **单次 commit**——任何失败（含 settle 写入失败）整体回滚：ledger 回到 manual_reconciliation、无审计残留、冻结保留，管理员可安全重试；run 尚有其他未收敛 ledger（barrier 未通过）时提交当前 ledger 与审计、保留冻结——**settle 由统一 finalizer 在 run 进入执行终态且 barrier 通过后完成（R17/P0，R18/P0：不得假设“最后一条收敛”是结算触发点——收敛时 run 可能未终态，终态后仍可能有收敛/beat 重试路径触发 finalizer）**；**禁止两段式**："CAS 先提交、settle 后提交"在 CAS 提交后、settle 提交前进程崩溃会留下不可恢复的永久冻结窗口（ledger 已终态、active freeze 未结算/释放、管理员重试 CAS 因状态已变返回 409、无补偿任务可触发）；**补偿不依赖结算意图 outbox 表而依赖 beat 扫描器（R18/P0 修正 R17“另建 settlement intent/outbox + 扫描器，本版不选，KISS”立场）**：run 行的执行终态 + `billing_finalized_at` 本身即结算意图记录，`billing_finalizer_scan` 定期重试不引入新表、仍是 KISS；④**测试**覆盖：未授权操作（非管理员 403）、证据缺失（reason/evidence 空被拒）、succeeded 缺 quantity/quantity≤0 被拒（422，CHECK 前校验）、初始 quantity=NULL 的 ledger 人工确认成功合法转 succeeded（真实 PostgreSQL，CHECK 放行）、重复操作（第二次 CAS rowcount=0 → 409）、两个管理员并发处理同一 ledger（仅一个成功）、故障注入①：CAS 成功后 settle 前抛异常 → CAS 与审计一并回滚、ledger 回 manual_reconciliation、可再次请求成功（R16/P1-1）、故障注入②：settle 写入失败 → 整体回滚、重试后最终只产生一条 settle 事件并释放冻结（R16/P1-1）、收敛后锁内 strict barrier + 最终 settle 正确（§6 验收 80 / §7 测试）、**证据单调（R17/P1-1）**：result_persisted 收敛不倒退为 post_call、已有 provider_request_id 传入不同值 409/422 且原证据不被覆盖、审计结构化字段与原/新值一致、recovery_method='manual'、**run 未终态人工收敛只提交 ledger 与审计不 settle、run 终态后 finalizer 结算含全部 ledger（R17/P0）**、**真实 PostgreSQL 双会话：人工收敛 finalizer 与 worker 新建下一条 pending ledger 并发——断言不可能出现“settle 在先、ledger 在后”（run 行锁串行化，R17/P0）**、**worker 终态关账 × 人工收敛同一 ledger（R20/P1-1）**：会话 A worker 终态事务按证据关账 pending ledger X、会话 B 人工收敛同一 ledger X 并发交错——两路径均按统一三层锁序（账户锁 → run 锁 → ledger 锁）推进，断言无死锁且仅一方成功修改该 ledger（另一方 CAS rowcount=0 或锁后重校验失败回滚/409，不产生双写）；另断言收敛入口实现不在账户锁/run 锁前对 ledger 加锁（代码级检查项），且无锁预读值不出现在任何状态/证据判断中（全部锁后重做，R21/P2-3）、**计费账户一致性（R17/P1-3）**：freeze resource_id/billing_key/run_id 任一不匹配拒绝收敛；冻结后项目所有者变化仍结算原账户（billing_account_user_id 不变）、**定价事实补齐（R17/P1-4）**：NULL pricing_key/billing_snapshot_id 的历史记录人工确认可补齐转 succeeded（快照校验通过）（§6 验收 80 / §7 测试）。
- `AudiobookProject.engine_config_snapshot`/`snapshot_status`：**加 CHECK 约束 `snapshot_status IN ('frozen','legacy_unfrozen','legacy_unverified')`（三态值域，R8）、`(snapshot_status='frozen') → engine_config_snapshot IS NOT NULL`、`(snapshot_status='legacy_unfrozen') → engine_config_snapshot IS NULL`**（§2.1，数据库层杜绝"标为 frozen 但无快照"的非法状态与任意字符串状态值）。
- **历史 ledger 迁移（R17/P1-4，施加收紧 CHECK 前必须完成）**：扫描 `billing_usage_ledger` 中 `status='succeeded'` 且（`pricing_key IS NULL` OR `billing_snapshot_id IS NULL`）的历史记录——优先从所属 run 的 `run_input_snapshot.billing_context.billing_snapshot` 确定性恢复（snapshot_id 可匹配且 pricing_key 存在于 `prices`，恢复即回填两列）；**无法恢复的置 `status='manual_reconciliation'`**（显式进入人工对账、拒绝自动结算，而非 NULL 静默放行——缺定价事实的 succeeded 记录无法计算金额却会被 strict barrier 放行，R17/P1-4；人工收敛接口支持对这类记录补齐 `pricing_key`/`billing_snapshot_id` 后转 succeeded，见记录规则）；历史 `unit` 非 `second`/`char` 值域的行同样清洗归一化，无法归一的置 `manual_reconciliation`；全部清洗完成后才施加 `ck_billing_usage_ledger_succeeded_fields` 收紧版与 `ck_billing_usage_ledger_unit` 新 CHECK。
- 迁移完成后执行全量校验（抽查历史批次 `engine_mode`/`engine_config_snapshot` 非空比例）。

#### 1.2 `backend/app/services/audiobook/project_audio_config.py` 引擎分支化

- 新增 `get_engine_branch(config, engine_mode)` / `set_engine_branch(config, engine_mode, branch)`：读写 `engines.{mode}`；读取时旧顶层 `characters`/`audio_fx`/`tts_models` 归一化为 `legacy_stems` 分支（只读回退，不就地改写）。
- `get_characters_for_model` / `set_characters_for_model` 增加 `engine_mode` 参数，实现 §2.2 读写优先级表（唯一事实规则）。
- `get_audio_fx` / `set_audio_fx` 增加 `engine_mode` 参数；`set_audio_fx` 停止写旧顶层。
- 新增 `get_scene_generation_preferences` / `set_scene_generation_preferences`（仅 `engines.seed_scene`，含 §2.2 历史 seed 键迁移映射）。
- 新增 `resolve_engine_mode(config)` 实现 §2.4 归一化规则（含旧 seed 键判定）。
- 新增 `build_engine_config_snapshot(config, engine_mode)` / `parse_engine_config_snapshot(raw)`（§2.1 结构，含 `engine_config_fingerprint` 计算）；新增 `build_run_input_snapshot(batch_snapshot, run_params, revision_heads)`（§2.1 完整运行输入）。

#### 1.3 API 合约与运行时解析器改造

- `backend/app/api/v1/projects.py`：`CharacterAudioConfig` 补充 `reference_source`/`reference_audio_url`/`voice_pool_publication_id`；新增 `EngineBranchConfig` 与 `ProjectAudioConfig.engines` 字段；`GET/PUT /{project_id}/audio-config` 按引擎分支读写；`POST /{project_id}/audio-config/auto-voices` 自动分配结果写入当前引擎分支。
- `backend/app/services/audiobook/project_audio_runtime.py`：`resolve_project_audio_runtime_config` 增加 `engine_mode` 入参，按分支解析（默认取 `resolve_engine_mode(config)`）；新增 `resolve_from_snapshot(snapshot)` 与 `resolve_from_run_input(run_input_snapshot)` 供运行期消费。

#### 1.4 批次创建冻结与复用规则

- 生成任务创建链路（`routes_projects.py`、`routes_tasks.py`、`routes_recover.py`、`routes_subtitle.py` 等 `audio_engine_mode=billing_context.audio_engine_mode` 处）：以 `resolve_engine_mode` 归一化结果写入 `engine_mode` 列与 `engine_config_snapshot` + `engine_config_fingerprint`。
- **复用判定**：`engine_mode` 一致且 `engine_config_fingerprint` 一致（规范化 hash 比较，审计元数据不参与）才复用 `AudiobookProject`，否则新建（§2.1）；两阶段流程（script_only → audio_from_scripts）未切换引擎时延用原批次，切换引擎后新建另一引擎批次并复制已审批剧本为新批次不可变快照（记录来源 batch/chapter_audio id）。
- **冻结范围**：批次创建时除 `engine_mode` 外，同步冻结规范化 `seed_audio_model` 与 provider 组合（seed/asr/fallback TTS 模型与 provider，§2.1 `engine_branch_config.providers`）入 `engine_config_snapshot`；生成链路（`_scene_render_mixin._seed_audio_model` 等）只消费快照中的规范化值，不读 `Project.audio_config.seed_audio_model` 实时值。
- `billing_context.audio_engine_mode` 同步改为由归一化结果驱动（`auto` 在计费前解析）。
- **run 创建事务（R8 同事务保证，P1-3；R9 扩展为冻结-派发闭环，P0-1；R10 事务所有权，P0-3；R11 账户锁 + outbox 派发意图 + 条件补偿，P0-2/P0-1/P1-4）**：**事务开头先取 `pg_advisory_xact_lock(user_id)`（账户锁，§2.9 锁序置顶），锁内重新聚合余额 + 全部有效冻结（含本批次全部 run）统一裁决**后再创建 `ChapterAudioRun`（含 `engine_mode_snapshot`/**`chapter_audio_id`（首次运行时先在同事务内创建/锁定唯一 active `ChapterAudio`——受 §1.1 部分唯一索引保护，并发插入 loser 按 §2.9 SAVEPOINT 协议回滚重读，R10/P0-4）**/`run_input_snapshot`/`revision_set_hash`/`input_signature`/**`dispatch_status='pending'`（R10/P0-1）**/**预生成固定 `celery_task_id`（唯一索引，R11/P0-1）**/**`predecessor_run_id`（上一 desired run id，R11/P1-4）**/**`dispatch_attempts=0`/`next_dispatch_at=now()`（R11/P0-1）**）+ 更新 `ChapterAudio.desired_run_id` + **同一事务内执行积分冻结**（`_safe_record_audiobook_billing_freeze` 不再吞异常：失败向上抛使事务整体回滚，run/指针/快照/冻结一并消失）必须在**同一数据库事务**内完成——不允许"先建 run 后补指针"或"先指指针后补快照"的中间可见状态；**R10 事务所有权（P0-3）**：`repository.create_run`/`create_runs`（约 948/990 行）、`create_task`（约 1172 行）、`attach_celery_id`（约 1183 行）、`enqueue_chapter_runs`（`task_support.py` 约 694 行）与计费 helper `_create_points_billing_event_log`（约 305 行）/`_safe_record_audiobook_billing_freeze` 的**内部 `db.commit()` 全部移除，只允许 `add`/`flush`**——事务所有权唯一归最外层应用服务，任何内部 commit 会把同事务未完成的 run/指针/快照/冻结提前提交（冻结后任一步异常均不得留下 task/run/指针/冻结事件残留，§7 测试）；**事务提交后派发由 dispatcher 兜底（R11/P0-1）**：run 行已带完整派发意图（`dispatch_status='pending'` + 固定 `celery_task_id` + `next_dispatch_at`）——**不再依赖"事务提交后立即同步 apply_async"这一易碎窗口**；入口仍可即时尝试派发，但即使进程在提交后崩溃，独立 dispatcher（beat 定时任务）租约认领 stale-pending 记录重放（CAS `dispatch_status='pending'` + `next_dispatch_at <= now()` + claim 过期，`dispatch_attempts+1`，超上限转 unknown，§2.1 第 4 步）；`apply_async` 三态处理：明确失败 → **锁定 `ChapterAudio` + 条件补偿**（`UPDATE chapter_audios SET desired_run_id = :predecessor_run_id WHERE id = :chapter_audio_id AND desired_run_id = :failed_run_id`——**rowcount=0 时 desired 已被更新 run 接管，只取消并释放失败 run、不覆盖新指针，R11/P1-4**；释放冻结/run 置 `cancelled`/`dispatch_status='cancelled'`）；**结果未知 → `dispatch_status='unknown'`，不释放冻结、不置 cancelled，走对账**（对账：查询 broker/任务状态，确认已执行则补记 `dispatched` 并保留 run，确认未执行才走补偿；长期未知由人工处理；禁止把 unknown 当确定未投递，P0-1）；成功 → `dispatch_status='dispatched'`；批量章节冻结阶段任一失败整体回滚、全部冻结成功才进入逐 run 派发阶段（§2.1 六步顺序）；**worker 侧**：任何供应商调用前必须租约认领（同事务 CAS 置 `status='running'` + `dispatch_status='dispatched'` + `claim_token`/`claimed_at`/`lease_expires_at`，rowcount=0 立即终止；heartbeat 续租；过期租约可接管；`task_acks_late`/`task_reject_on_worker_lost`/`visibility_timeout` 配置，§2.1 worker 租约协议）。
- 冻结语义：批次创建后 `engine_mode`、`engine_config_snapshot`、`engine_config_fingerprint`、`snapshot_status` 不再变更。

#### 1.5 消费方快照化（完整清单）

- `background_jobs_full.py` / `background_jobs_scripts.py`（**R9/P0-4，R10 分阶段冻结，P1-2：full 运行按阶段完成后分别冻结 `derived_execution_facts` 子项——剧本生成阶段完成后冻结 `generated_script_facts`（+ `generated_script_facts_hash`）、voice_binding 阶段完成后冻结 `voice_resolution`（+ `voice_resolution_hash`）、scene_planning 阶段完成后冻结 `scene_topology`（+ `scene_topology_hash`），恢复从最后一个完整阶段的下一阶段继续（不重跑已冻结阶段的非确定性过程、不读实时值），§2.11**） / `background_jobs_audio.py`：`_apply_project_audio_effects` 系列改从 `audiobook_project.engine_config_snapshot` 解析运行时配置，删除对 `project.audio_config` 的实时读取；**删除 `voice_mapping` 写回路径**（`background_jobs_scripts.py` 约 493-508 行），自动分配结果经音色持久化链路写入引擎分支（作为快照捕获内容）。
- **整章输出写回改造（R7，§2.4 规则 2/3/4）**：`background_jobs_shared.build_chapter_audio_output_path` 增加 `run_id` 参数（输出落 run 级路径）；`apply_chapter_audio_generation_result`/`generate_and_apply_subtitle_artifacts` **不再直写** `ChapterAudio.audio_path`/`duration`/`file_size`/`subtitle_path`/`subtitle_format`，改为写 run 级文件 + 插入/更新 `ChapterAudioOutput`（`status='staged'`）；章节完成回调统一走 §2.4 规则 4 **完整发布事务**（状态字段 + 整章元数据 + 输出登记 + artifact 状态机单事务原子完成），`routes_download.py` 下载链保持读 `ChapterAudio.audio_path`（发布事务写入的镜像列，值恒为已发布 run 的 run 级路径）。
- `task_support.py`（约 442 行恢复 payload 构造）、`routes_recover.py`（约 257 行）、`routes_subtitle.py`（约 173 行）：计费预检与恢复输入改以 `run_input_snapshot`（方案 A 自包含正文，§2.1/§2.11）为输入。
- `routes_segment_regen.py`（约 341 行）：`_resolve_segment_regeneration_runtime_config` 改从批次快照解析（缺快照的 legacy_unfrozen 批次拒绝片段级重新生成）。
- **补充以下遗漏路径：**
  - `routes_segment_preview.py`（约 65 行）：`resolve_project_audio_runtime_config` 改从批次快照解析，删除 `base_voice_mapping=audiobook_project.voice_mapping` fallback（用户切换音色后试听与批次不一致的问题）。
  - `background_jobs_remix.py`（约 898 行）：整章混音的 `resolve_project_audio_runtime_config` 改从批次快照解析；**输出写回改造（R8，§2.10 run_type 分类；R9 补发布谓词）**：删除"输出路径变化时 `_cleanup_previous_chapter_artifacts` 直接回收旧整章产物"（约 744 行）与直写 `ChapterAudio.audio_path`/`duration`/`file_size`/`subtitle_path`/`subtitle_format`（约 768 行）的路径，改写 run 级文件 + `ChapterAudioOutput`（staged）+ 运行结束写 `result_render_status='completed'` + §2.4 规则 4 发布事务（legacy 引擎发布谓词，§2.4 规则 4 c）——人工重混不再能删除当前已发布文件、不再绕过原子发布保证。
  - `routes_tasks.py`（约 166 行）：任务恢复计费预检改以 `run_input_snapshot` 为输入。
  - `routes_segment_regen.py`（约 589 行）：片段时间线试听/重新生成的第二个 `resolve_project_audio_runtime_config` 调用点改从批次快照解析。
- 场景重渲染入口：以 `revision_set_hash` + `run_input_snapshot` 为新运行输入——**在创建运行的同一事务内**读取当前已审批 `script_json` 与 revision heads 投影并冻结（§2.1 run_type 合同：audio_from_scripts/重渲染），随后执行只消费快照正文（R7）。
- 全仓 grep 清理剩余 `resolve_project_audio_runtime_config(project, ...)` 直传调用点，逐一点名迁移。

#### 1.6 章节状态查询按引擎过滤并返回三维投影状态

- `getAudiobookProjectsByProject` API（`backend/app/api/v1/audiobook_api/routes_projects.py`）支持可选查询参数 `engine_mode`：传入时仅返回匹配引擎的批次；**返回结构增加 `engine_mode` 与 `chapter_audios[].render_status`/`render_status_detail`**；不传时行为不变（兼容其他调用方）。
- `_serialize_chapter_audio_summary` 增加 render_status 字段。
- 前端两引擎使用不同的完成条件（§2.4），`resolveGeneratedChapterIds` 按引擎区分判定；seed_scene 侧返回三维投影状态而非二值。

### 阶段 2：前端布局与状态隔离

#### 2.1 引擎选择器移到章节队列卡片顶部

- `frontend/src/pages/audiobook/AudiobookSetupStep.tsx`：在第一个 SetupPanel（章节队列）内部顶部新增引擎切换区块（`audioEngineMode` + `onAudioEngineModeChange`），置于 `ChapterSelectionPanel` 之上。
- `frontend/src/pages/audiobook/NarrationAudioConfigPanel.tsx`：移除引擎 ToggleButtonGroup 及相关 props；`audioEngineMode === 'seed_scene'` 时不渲染 `AudioFxConfigPanel`（音效由生成过程决定），仅保留输出格式。

#### 2.2 角色音色绑定与创作偏好按引擎分支持久化

- `frontend/src/pages/AudiobookPage.tsx`：项目加载时按 `audio_engine_mode` 读取对应分支的 characters（含 tts_models 归组与 `reference_source` 等字段）填充 `characterVoices`；保存路径（`handleVoiceChangeAndPersist` 等）经 `buildProjectAudioConfigPayload` 写入当前引擎分支的 `engines.{mode}.tts_models.{model}.characters`。
- `frontend/src/pages/audiobook/projectAudioConfigUtils.ts`：`buildProjectAudioConfigPayload` 改为输出 `{ audio_engine_mode, engines: { [mode]: { tts_models, audio_fx|scene_generation_preferences } }, ... }`；解析侧读分支。
- 切换引擎时重新加载目标分支绑定与创作偏好并刷新 `characterVoices`。

#### 2.3 章节状态按引擎过滤并升级为结构化状态

- `frontend/src/pages/audiobook/chapterSelectionUtils.ts`：`resolveGeneratedChapterIdsFromProjects` 增加 engine_mode 过滤，区分两引擎完成条件；新增 `resolveChapterStateById(projects, engineMode)` 返回 `Record<number, ChapterRenderState>`（`{renderStatus, executionStatus, audioUrl, locked, exportable}`）。
- `frontend/src/pages/audiobook/useAudiobookGeneratedChapterIds.ts`：hook 增加 `engineMode` 入参并返回 `chapterStateById`（不再只返回 `Set<number>`；`generatedChapterIds` 由 `chapterStateById` 派生，向后兼容现有消费方）。
- `frontend/src/pages/AudiobookPage.tsx`：把 `audioEngineMode` 传入 hook；章节列表 Chip 按章节状态表渲染（published 四值 {rendered_all_seed, rendered_with_fallback, stale, null} + desired 专属态 {manual_review_required, failed} 的展示组合，R11/P2-1；外加进行中 execution_status）。

#### 2.4 生成编排入口分流

- `backend/app/services/audiobook/engine_pkg/_generation_mixin.py`：**入口处（`formulate_strategy` 之前）** 按 `engine_mode` 分流——`seed_scene` 跳过 `AudioDirector.formulate_strategy()` 与 `_apply_audio_fx_to_strategy()`，直接进入场景导演链路。
- `backend/app/services/audiobook/engine_pkg/_audio_from_script_mixin.py`：同样在入口按 `engine_mode` 分流。
- `backend/app/services/audiobook/engine_pkg/_parallel_mixin.py`：`prepare_render_assets` 由管线根据 `engine_mode` 确定（`seed_scene` → 恒 False），不依赖调用方传参。
- `seed_scene` 入口不传递 `sound_effect_density`/`music_density` 等旧策略参数。

#### 2.5 三维投影状态聚合写入与回退完成语义修正

- `_scene_render_mixin.py`：整章装配完成后**先写 `ChapterAudioRun.result_render_status`/`result_render_detail`（本次结果，无论是否发布，§2.4 三维投影）**，再按 §2.4 规则 4 **幂等完整发布协议（R8，R9 修订）**——锁行 → 幂等短路（`published_run_id = :run_id` 且签名相同，**先经 R9 最低一致性检查：published 登记存在 + 镜像列字段齐全 + 物理文件存在，损坏不短路，P2-1**）→ 发布前置校验（run 归属与终态/**发布谓词按引擎（R9/P0-2）**：seed_scene 要求 `result_render_status ∈ {rendered_all_seed, rendered_with_fallback}`、legacy_stems 系要求 `result_render_status = 'completed'` 且整章输出齐全；staged 输出恰一条；**artifact 完整性增强（R9/P1-4）：场景键集合全等 + 每场景恰一条 staged + scene_topology_hash/segment_keys/content_digest/物理文件存在性/source_kind fallback 合同逐条校验**）→ CAS 镜像列（`WHERE id = :chapter_audio_id AND desired_run_id = :run_id`，rowcount==0 立即结束）→ 输出登记切换（旧 superseded **显式排除 `run_id <> :run_id`**，本 run staged→published）→ artifact 状态机（**`chapter_audio_id` 作用域，排除本 run**）→ 单事务提交；**seed 可发布状态集仅 `rendered_all_seed`/`rendered_with_fallback`**（`manual_review_required`/`failed` 不进入发布 SQL——失败不改变旧已发布产物，与 §2.4 规则 5 一致；`stale` 由基线失配检测派生）；存在回退场景时不再无条件返回 `success: true`，返回聚合状态与 `local_fallback_count`。**入队/重渲染不前置清空 render_status**（旧已发布产物保持可导出）。
- `render_status_detail` 记录 `local_fallback_count`、`manual_review_scene_ids`、`terminal_policy`。
- 导出与计费判定读 `render_status`（§2.4 表）；`stale` 状态由 `_derive_chapter_audio_stale` 类既有逻辑扩展（新增 script/topology hash 失配检测）。

### 阶段 3：章节编辑器分流与场景编辑器

#### 3.1 点击章节分流（多批次选择）

- `frontend/src/pages/AudiobookPage.tsx` `onOpenGeneratedChapter`：按 §2.5 选择规则定位批次（扩展 `resolveAudiobookProjectIdForChapter` 返回批次、engine_mode 与 render_status，替换"取第一个"逻辑）；`legacy_stems` → 现有 `handleOpenScriptEditor`；`seed_scene` → 打开新场景编辑器状态（新增 `sceneEditorChapter`/`sceneEditorOpen` 等 state）。
- 场景编辑器内提供批次切换器（同引擎多批次时）。

#### 3.2 后端场景编辑接口（新文件 `backend/app/api/v1/audiobook_api/routes_scene_editor.py`）

**资源标识统一使用 `audiobook_project_id`**（与 `routes_script.py` 一致），所有端点经 `get_owned_audiobook_project` 校验批次归属与章节从属（章节必须属于该批次所属源项目）：

- `GET /audiobook/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/editor-document`：聚合 `script_json`（审定台词，含 segment_key）、`ChapterAudioRun.checkpoint_json` 的场景结果列表、`SceneEditRevision` 链投影（导演覆盖/音色绑定）为 `SceneEditorDocument`；返回场景列表（scene_id/status/action/attempts/**scene_audio_url**/quality_report）+ 分段归属 + 章节音频 URL + 三维投影状态（execution_status + published_render_status + desired_render_status + published_provenance，R10/P2-1 命名统一）。
- `PUT ...?edit_type=dialogue`：台词编辑接口——请求体携带 `base_revision_hash` 与修改后的台词分段；原子并发校验（§2.9，失配 `409 Conflict`）；经 `_sanitize_incoming_script_segments` 净化后写回 `script_json`；语义变化时**自动重置 `script_status='pending'` 并清空 `script_review_json`/`final_audio_review_json`/`segment_reviews_json`**；**不删除 checkpoint**。
- `PUT ...?edit_type=director_override`：导演覆盖接口——payload 含 `{scene_id, stable_anchors, overrides}`（§2.6），写入 `SceneEditRevision`；**不修改 `ScriptSegment.text`**。
- `PUT ...?edit_type=voice_binding`：音色绑定接口——**双写（R7 局部覆盖语义；R9 并发锁，P1-6；R10 全局锁序，P1-4）**：同一事务内先 `SELECT ... FROM projects WHERE id = :project_id FOR UPDATE` 锁定 Project 行（或配置版本 CAS）→ **再按全局锁序锁当前章节 `ChapterAudio` 行（`SELECT ... FROM chapter_audios WHERE id = :chapter_audio_id FOR UPDATE`）→ 最后锁 voice_binding head**（`Project → ChapterAudio → heads` 固定顺序，与 dialogue 编辑/审批一致，R10/P1-4）→ 更新 `Project.audio_config.engines.{mode}.tts_models.{model}.characters`（复用现有音色持久化链路，**仅作为未来批次默认值**）+ 写 `SceneEditRevision`（edit_type=voice_binding，当前章节覆盖，§2.6）+ 更新 head + **仅当前章节**的已发布产物置 stale（`stale_reason = voice_binding_changed`），同批次其他章节不置 stale——不同章节并发 voice_binding 双写被串行化，失败整体回滚，不产生分裂状态。
- `POST .../dialogue-review`：**dialogue 审批端点（R8，§2.9 审批闭环）**——请求体 `{verdict: "reviewed" | "approved", review_json, base_revision_set_hash}`；并发基线失配 `409`；`pending → reviewed → approved` 状态机；审核证据写 `ChapterAudio.script_review_json` + 新增 `script_review_version`；approved 后允许发起 `audio_from_scripts`/场景重渲染（死锁解除，§2.9）。
- 四个端点成功后均更新对应记录：三类编辑端点创建 `SceneEditRevision` 行 + 更新 `scene_edit_revision_heads` 行（§2.9 原子事务），返回 `{revision_heads, revision_set_hash}`；dialogue-review 端点不产生 revision（仅审核证据与状态迁移）。
- **旧脚本接口统一拒绝**：`routes_script.py` 的 `PUT /script` 对 seed_scene 批次拒绝直写并返回 `409/400`（提示走场景编辑器）；legacy_stems 批次保持现状。
- **媒体授权**：`SceneEditorDocument` 与场景列表不返回本地 `audio_path`，仅返回经权限验证的 `scene_audio_url`（带 play_token）。
- 重渲染入口：复用既有章节生成任务接口，传递 `revision_set_hash`；服务端以 `run_input_snapshot`（方案 A 自包含正文）创建新 `ChapterAudioRun`。

#### 3.3 `SceneEditorDocument` 数据模型

`SceneEditorDocument` 是编辑视图的稳定投影，由多个数据源聚合而成，**不是直接编辑 checkpoint**：

```python
class SceneEditorDocument:
    chapter_id: int
    audiobook_project_id: int
    engine_mode: str = "seed_scene"
    execution_status: str                    # §2.4 维度一（聚合自 ChapterAudioRun.status）
    published_render_status: str | None      # §2.4 维度二（ChapterAudio.render_status 的 API 投影名，R9/P1-5 唯一化）
    desired_render_status: str | None        # desired_run_id 对应 run 的 result_render_status（R8 三维投影，§2.4）
    published_provenance: str | None         # published | legacy_unverified（R10/P1-1：历史回填产物显式进入 schema，不可误读）
    source_script_revision: str              # script_json hash
    director_plan_revision: str | None       # director 计划 hash
    scene_topology_hash: str                 # 场景拓扑 hash（§2.6 canonical 合同）
    scenes: list[SceneEditorScene]           # 场景定义（含 scene_audio_url、segment_keys）
    editable_overrides: dict                 # SceneEditRevision 链投影的当前覆盖（含稳定锚点）
    artifact_references: dict                # 音频/字幕 URL 引用（非本地路径）
    last_revisions: dict                     # 三条链 head 的完整投影（§2.9）
    updated_at: datetime
```

- `GET` 由 `ScriptSegment`（含 segment_key）、Director plan、checkpoint、`SceneEditRevision` 链尾与 `SceneAudioArtifact` 聚合生成。
- `PUT` 校验 `last_revisions[?edit_type]` → 创建 revision/override，不编辑 checkpoint 本身。

#### 3.4 场景音频 artifact 登记与试听端点

- 渲染完成后在 `_scene_render_mixin.py` 装配段登记 `SceneAudioArtifact`（复制场景音频到 `backend/data/scene_audio_artifacts/`，写 `content_digest`/`segment_keys`/`scene_topology_hash`/`source_kind`，**`status='staged'`**，**登记时写入 `chapter_audio_id`（R8 发布作用域）**；fallback 产物同样登记，来源标记）；**artifact 状态机跟随发布事务（R7/R8，§2.4 规则 4 g）**：仅在完整发布事务内 staged → active，旧已发布 run 的 active artifact 以 `chapter_audio_id` 为作用域同步 superseded（置 `deleted_at`，**显式排除 `run_id = :run_id`**，其他批次/引擎的 artifact 不受影响）；失败/未发布 run 的 artifact 保持 staged，不激活。
- 新端点 `GET /audiobook/scenes/{artifact_id}/stream`（`routes_scene_editor.py` 或 `routes_download.py`）：权限校验（批次归属 + 章节从属 + `status = 'active'` 且 `deleted_at IS NULL`）+ 短期 `play_token`（复用 `_create_stream_access_token` 模式）。
- 新端点 `GET /audiobook/scenes/{artifact_id}/audit-stream`（仅管理员/项目所有者，不限 `deleted_at` 与 `status`）。
- 章节重渲染替换场景后旧 artifact 经发布事务置 `status='superseded'` + `deleted_at`（R7），物理文件按保留策略（§8）清理；运行目录清理不影响试听。

#### 3.5 前端场景编辑器（新组件 `frontend/src/pages/audiobook/SceneChapterEditor.tsx`）

- 场景列表：scene_id、状态 Chip（passed/manual_review/legacy_stems/stale）、时长、试听按钮（`scene_audio_url`）。
- 场景详情：三段式编辑区——①台词编辑（修改台词文本，走 `edit_type=dialogue`，触发保真审计与 script_status 重置提示）、②导演覆盖（表演/音效/音乐指令，走 `edit_type=director_override`，不修改原文）、③音色编辑（复用角色声音面板）。
- 保存时携带 `base_revision_hash`（来自 `last_revisions[?edit_type]`）；`409 Conflict` 时提示"文档已被他人修改，请刷新后重试"。
- 保存成功提示（服务器返回 `revision_heads`）、章节音频总试听。
- 复用既有播放器 `useAudiobookAudioPlayback.playExternalUrl` 与试听错误处理。
- `frontend/src/pages/audiobook/AudiobookSetupStep.tsx`：按当前引擎渲染剧本编辑器或场景编辑器；保存成功后刷新 `chapterStateById` 与项目详情。
- `frontend/src/pages/audiobook/types.ts`：新增 `SceneEditorDocument`、`SceneEditorScene`、`SceneDirectionOverrideItem`（含 stable_anchors）、`SceneEditRevision`、`EngineBranchConfig`、`ChapterRenderState` 等类型。

#### 3.6 路由注册

- 新路由文件 `routes_scene_editor.py` 必须加入 `backend/app/api/v1/audiobook_api/__init__.py` 的显式 import 列表（与既有 routes_* 一致），否则端点不生效。

## 6. 验收标准

1. 页面左侧第一张卡片顶部出现生成引擎切换，切换后章节状态立即按引擎刷新。
2. `seed_scene` 生成第 1 章后切换到 `legacy_stems`：第 1 章显示为"从未生成过"；切回 `seed_scene` 恢复。
3. 两引擎下同一角色可配置不同音色绑定（含 tts_models 归组与 reference_source），互不覆盖；切换引擎后角色声音面板加载对应分支。
4. `seed_scene` 模式下音效/配乐面板隐藏，`legacy_stems` 模式行为不变。
5. 点击 `seed_scene` 已生成章节进入场景编辑器（场景列表 + 三段式编辑 + 试听）；点击 `legacy_stems` 已生成章节进入原剧本编辑器；同章多批次时编辑器可切换批次。
6. 场景编辑按类型分流：台词编辑走 `script_json`（触保真审计 + `script_status` 重置 pending）、导演覆盖走 `SceneEditRevision`（不修改原文）、音色绑定**双写** `SceneEditRevision` + `audio_config`（当前章节局部覆盖 + 未来批次默认值，§2.6；**仅当前章节**已发布产物置 stale）。
7. 任意场景编辑不删除或覆盖历史 checkpoint；编辑历史落在 `scene_edit_revisions` 表（append-only）+ `scene_edit_revision_heads`（可 UPDATE head 指针）。
8. 恢复任务只消费 `run_input_snapshot`（方案 A 自包含正文，**按 run_type 合同**）恢复，不读取项目当前活跃引擎与实时配置；`full`/`script_only` 恢复依赖 checkpoint（`script_facts` 为 null），`audio_from_scripts`/场景重渲染恢复以快照内嵌 `script_facts` 正文重建输入。
9. 两引擎完成条件独立：`legacy_stems` 按 `script_json + audio_path + script_status`；`seed_scene` 按三维投影状态（`execution_status` + `published_render_status` + `desired_render_status`，R10/P2-1 命名统一）。
10. `seed_scene` 成功路径不调用旧 `AudioDirector`/`SoundEffectDesigner`/`MusicComposer`/逐句 TTS；`SceneAudioAssembler` 场景拼接正常工作。
11. 旧数据（顶层 characters/audio_fx/tts_models、无 engine_mode 批次、旧 seed 键）读取不报错，默认归属 `legacy_stems`；迁移后历史批次 `engine_mode` 非空、`engine_config_snapshot` 全部非空（仅 legacy_unfrozen 解析失败除外——legacy_unverified 仍写入推导快照）。
12. Alembic 迁移后历史批次 `engine_mode` 全部非空、`engine_config_snapshot` 全部非空（仅 legacy_unfrozen 可空）；**迁移一次性证据判定写最终值，不存在"先全量回填 legacy_stems 再推断"的中间步骤**；`legacy_unverified`/`legacy_unfrozen` 批次恢复被拒（`legacy_unverified` 允许推导快照或 null，均禁止恢复）；有 checkpoint/运行参数/billing 证据的批次为 `frozen`；**值域 CHECK 生效（R8）：`snapshot_status ∈ {frozen, legacy_unfrozen, legacy_unverified}`，`frozen` 必须有快照、`legacy_unfrozen` 必须无快照**；**snapshot_status 迁移顺序与显式写入（R19/P2-1）**：`snapshot_status` 无 server_default——迁移按"新增可空列（无默认）→ 按证据回填 → 校验无非法组合 → 置 NOT NULL + 三态 CHECK"顺序执行（断言中间态不存在默认 frozen 的历史行）；应用服务创建批次时显式写 `snapshot_status`；绕过应用服务且不带 snapshot/status 的插入因 NOT NULL 失败（不会被误标 frozen）。
13. 任务入队后切换引擎：进行中/已暂停任务仍按原快照执行与计费（A 快照计费、A 快照执行）。
14. 并发编辑：携带过期 `base_revision_hash` 的 PUT 返回 `409`，不覆盖先保存者；两个并发请求不会形成分叉链（head 表唯一约束 + 行锁 + **复合外键作用域**）；**幂等闭环（R7）**：候选 hash 以请求携带的 `base_revision_hash` 为 parent 计算——同一请求（同 base 同内容）重复提交、网络重试、并发 loser 重读 head 后均返回原 revision 而非 409；**并发 loser 经 SAVEPOINT 恢复协议（R8，R9 精确写法）**：真实 PostgreSQL 双事务并发下，loser 捕获 `IntegrityError` 后 `nested.rollback()` **回滚到 SAVEPOINT**（严禁 `session.rollback()`——终止外层事务）再重读 head（不抛 `InFailedSqlTransaction`），按候选 hash 判定幂等成功或 409；head 被后续编辑推进后重试原请求按新 base 刷新后提交。
15. 场景编辑器所有音频引用为 URL（无本地绝对路径泄露）；未授权用户访问试听端点返回 403/404；任务运行目录清理后试听仍可用（artifact 登记）。
16. 带回退场景的章节状态为 `rendered_with_fallback`（防覆盖锁定、可导出、**仍可进入场景编辑器提交 revision 与发起重渲染**、标记"含回退场景"），计费按 seed + 回退 TTS 拆分。
17. dialogue 编辑语义变化后 `script_status` 自动回到 `pending`，旧审定结果清空（`script_review_json`/`script_review_version`），重新审定前不可直接导出；**审批闭环（R8）**：`POST .../dialogue-review` 按 `pending → reviewed → approved` 状态机审批（verdict=reviewed/approved，可一次性直批），携带 `base_revision_set_hash` 并发基线（审批期间有新编辑返回 409），审核证据写 `script_review_json` + `script_review_version`；approved 后可发起重渲染，死锁解除。
18. `seed_scene` 批次经旧 `PUT /script` 直写被拒绝（统一返回 409/400，提示走场景编辑器）。
19. `run_input_snapshot` 为方案 A 自包含正文（引擎配置 payload + 剧本事实/原章输入正文 + 音色解析正文 + 编辑基线投影正文 + run_options + billing_context 含 provider 组合与不可变 `billing_snapshot` 计价事实 + input_signature），**按 run_type 合同冻结**：`audio_from_scripts`/场景重渲染在创建运行同一事务内读已审批 `script_json` 与 revision heads 投影；`full`/`script_only` 冻结原章 `content`（`script_facts` 为 null）；修改 `Project.audio_config` 或 `ChapterAudio.script_json` 后，恢复仍按快照正文执行。
20. 审计端点 `GET /scenes/{artifact_id}/audit-stream` 允许管理员访问已 superseded/软删除的 artifact，与普通 `stream` 端点的 `status = 'active'` 且 `deleted_at IS NULL` 约束分离。
21. **幂等完整发布（R8，R9 修订）**：新 run 入队/失败不改变旧已发布产物（`published_run_id`/`render_status`/`audio_path`/`duration`/`file_size`/`subtitle_path` 全部不变）；完成时单事务按 §2.4 规则 4 八步协议发布（**锁行 → 幂等短路（先经 R9 最低一致性检查：published 登记存在 + 镜像列齐全 + 物理文件存在，损坏不短路）→ 前置校验（run 归属/终态/**发布谓词按引擎**——seed_scene：`result_render_status ∈ {rendered_all_seed, rendered_with_fallback}`；legacy_stems 系（含 chapter_remix）：`result_render_status='completed'` 且整章输出齐全；staged 恰一条/**artifact 完整性增强（场景键全等 + 每场景恰一条 staged + 拓扑/锚点/digest/文件存在性/fallback 合同））→ CAS 含 `id`（`WHERE id = :chapter_audio_id AND desired_run_id = :run_id`）→ 旧输出 supersede 显式排除 `run_id <> :run_id` → staged→published → artifact 以 `chapter_audio_id` 为作用域切换 → 单事务提交**）；**完成回调重试幂等**：重复回调命中幂等短路直接返回，不二次 supersede；CAS 未命中（rowcount=0）立即结束；seed `failed`/`manual_review_required` 不进入发布 SQL；**legacy 引擎（full/audio_from_scripts/chapter_remix）`result_render_status='completed'` 可发布（R9/P0-2）**。
22. `seed_audio_model` 与 provider 组合参与 `engine_config_fingerprint`：`seed-audio-1.0` 与 `seed-audio-1.0-multilingual` 或不同 provider 产生不同 fingerprint，不复用同一批次；生成链路消费快照中冻结的规范化值，不读顶层实时值。
23. **计费事实冻结（R8，R9 扩展六步闭环，R10 事务所有权）**：按六步顺序执行——①入队前捕获不可变 pricing snapshot（每 run 独立）→ ②准入预检（snapshot 计价事实 + 实时账户余额）→ ③同一事务创建 run + 持久化快照 + 更新 `desired_run_id` **+ 同事务冻结**（**R11/P0-2：事务开头 `pg_advisory_xact_lock(user_id)`，锁内重聚合余额 + 全部有效冻结后统一裁决本批次冻结**；R9/P0-1：冻结失败整体回滚；**R10/P0-3：整个入队调用图（`repository.create_task`/`attach_celery_id`/`create_run`/`create_runs`、`task_support.enqueue_chapter_runs`、`_create_points_billing_event_log`/`_safe_record_audiobook_billing_freeze`）内部 `db.commit()` 全部移除，只允许 add/flush，事务归最外层应用服务；冻结后任一步异常不留 task/run/指针/冻结事件任何残留**）→ ④**事务提交后派发由 dispatcher 兜底**（R11/P0-1：run 即 outbox——派发意图 + 固定 `celery_task_id` 同事务落库，stale-pending 扫描器租约认领重放；R10/P0-2：每 run 独立 Celery 消息 + 独立 task id；三态：明确失败→**条件补偿（锁定 ChapterAudio + `UPDATE ... WHERE desired_run_id = :failed_run_id`，rowcount=0 不覆盖新指针，R11/P1-4）**、**结果未知→`dispatch_status='unknown'` 不释放冻结走对账（P0-1）**、成功→`dispatched`）→ ⑤**批量章节策略**（冻结阶段任一失败整体回滚；派发阶段逐 run 独立补偿/对账，已成功派发者不受影响）→ ⑥结算（run 快照内嵌 snapshot + **`billing_usage_ledger` 实际用量，R9/P1-3；R10/P1-3 调用前 pending → 成功转 succeeded 状态机；**R11/P1-2 四态：确定失败转 confirmed_failed、无法判定转 manual_reconciliation，均不自动结算**）；预检/冻结/结算只消费 `billing_context.billing_snapshot` 内嵌计价事实（各 provider/model 单价、计价单位、`user_price_basis`/`user_price_rate`/`provider_discount_capture_rate`/`provider_discount_rate`/`provider_discount_source`/`points_per_yuan`/`freeze_buffer_rate`/`margin_warning_rate`/`negative_margin_block_enabled`/`settlement_formula_version`，对齐 `PointsPricingPolicyConfig`/`PointsBusinessSettlementSnapshot` 实际字段）；**计费作用域为 run 级（R8，R9 统一命名）**：`build_audiobook_billing_key` 为 `audiobook:{audiobook_project_id}:run:{run_id}`（不再使用含义不清的 `{project_id}`，源小说 project_id 仅展示聚合），同批次多次运行各自冻结/结算/幂等，批次级账单仅展示聚合；修改定价策略或用户账户层级后，已入队任务的预检与结算结果不变。
24. **revision 数据完整性（R7）**：`parent_revision_id` 为唯一事实（hash 经 JOIN）；head 表复合外键拒绝"本章节 head 指向另一章节/另一链 revision"；插入跨作用域 parent 被数据库拒绝（复合外键生效）。
25. **复制合同持久化（R7）**：切换引擎复制剧本后，新批次 `ChapterAudio` 含 `source_script_hash`/`source_script_review_version`/`source_provenance_json` 且与源脚本 hash 一致；复制后新批次可无阻碍执行 `audio_from_scripts`；运行期与源批次互不依赖。
26. **锁定语义（R7）**：`rendered_all_seed`/`rendered_with_fallback` 章节禁止覆盖式初始生成与直接修改已发布产物，但场景编辑器可正常提交三类 revision 并触发重渲染（新 run）。
27. **发布重试幂等（R8）**：完成回调重复触发（网络重试/幂等键重放）时，命中幂等短路直接返回已发布结果，不产生二次 supersede、不报错；CAS 未命中（`desired_run_id` 已指向其他 run）时发布步骤全部跳过。
28. **artifact 发布作用域（R8）**：同一源章节存在于多个 AudiobookProject（legacy_stems/seed_scene/同引擎多批次）时，发布任一 run 仅 supersede 该 `chapter_audio_id` 下其他 run 的 artifact，其他批次/引擎的 active artifact 不受影响；复合外键拒绝跨运行作用域的 artifact 登记。
29. **三维状态投影（R8）**：状态接口与 `SceneEditorDocument` 同时返回 `published_render_status`/`desired_render_status`/`execution_status` 三维——首次 `manual_review_required` 未发布时 `published_render_status` 为 null、`desired_render_status` 展示本次人工评审结果；重渲染失败时前端不再误显旧 `rendered_all_seed`。
30. **remix 纳入发布体系（R8）**：`chapter_remix` 输出落 run 级路径 + `ChapterAudioOutput`（staged）+ §2.4 发布事务；`_cleanup_previous_chapter_artifacts` 直接回收旧整章产物与直写 `ChapterAudio` 字段的路径已删除，旧产物仅经发布事务 supersede + §8.3 清理策略回收。
31. **dialogue 审批闭环（R8）**：编辑 → pending → `dialogue-review` 审批（reviewed/approved）→ approved 后可发起重渲染；审批携带 `base_revision_set_hash` 并发基线（失配 409）；审核证据持久化 `script_review_json` + `script_review_version`；审批后再次编辑重置 pending 且清空审核证据。
32. **run 级计费（R8，R9 统一命名）**：同一批次多次重渲染时各 run 独立捕获计价事实、独立冻结与结算（`audiobook:{audiobook_project_id}:run:{run_id}`），互不干扰、各自幂等；批次级账单正确聚合各 run 事件。
33. **run 级输出清理（R8）**：superseded/staged 且 run 已终态的 `ChapterAudioOutput` 与整章文件（audio/subtitle）超保留期被回收，published 输出不清理；运行目录清理后试听与导出不受影响。
34. **冻结-派发闭环（R9/P0-1，R10 可靠派发，R11 outbox + 条件补偿 + 租约）**：同一事务完成"账户锁 + 重聚合 + 建 run + 快照 + 指针 + 冻结"（**R11/P0-2：事务开头 `pg_advisory_xact_lock(user_id)`，锁内重聚合余额 + 全部有效冻结 + 本批次全部冻结统一裁决——两个并发请求分别通过预检后，冻结总额不得超过余额**；R10：全链路 add/flush、冻结后任一步异常无任何残留），冻结失败事务整体回滚（不产生"未冻结先执行"）；**事务提交后派发由 dispatcher 兜底（R11/P0-1：run 即 outbox——派发意图 + 固定 `celery_task_id` + `next_dispatch_at` 同事务落库；stale-pending 扫描器租约认领重放，`dispatch_attempts` 超上限转 unknown 人工对账，不再依赖"提交后立即 apply_async"窗口）**；逐 run 派发（R10/P0-2：每 run 独立消息 + 独立 task id，不再整批共用一个 signature）；派发三态：明确失败 → **条件补偿（锁定 ChapterAudio + `UPDATE ... SET desired_run_id = :predecessor_run_id WHERE id = :chapter_audio_id AND desired_run_id = :failed_run_id`，rowcount=0 只取消释放失败 run、不覆盖新指针，R11/P1-4；释放冻结/run 置 `cancelled`/`dispatch_status='cancelled'`）**，**结果未知 → `dispatch_status='unknown'`、不释放冻结、不置 cancelled、走对账**（禁止把 unknown 当确定未投递——broker 已接收而响应丢失时，补偿会释放已退款任务的冻结而 worker 仍执行），成功 → `dispatched`；**worker 消费租约（R10/P0-1，R11/P1-1）**：任何供应商调用前 CAS 租约认领（status pending/queued → running + dispatch_status → dispatched + claim_token/claimed_at/lease_expires_at），rowcount=0 立即终止不调用供应商——已退款/已取消任务不再产生供应商费用；heartbeat 续租、过期租约接管、先落库后 ACK；批量章节冻结阶段任一失败整体回滚、全部冻结成功才进入逐 run 派发阶段。
35. **发布谓词按引擎（R9/P0-2）**：legacy_stems（full/audio_from_scripts/chapter_remix）运行 `result_render_status='completed'` 且整章输出文件齐全即可发布，不依赖 Seed 渲染状态；seed_scene 仍要求 `rendered_all_seed`/`rendered_with_fallback`。
36. **运行作用域闭合（R9/P0-3，R10 补唯一约束 P0-4）**：`ChapterAudioRun.chapter_audio_id` 不可变；runs 复合唯一键 `(id, chapter_audio_id)`；output/artifact 复合外键与 `ChapterAudio` 双指针复合外键均指向该键——跨章节/跨实例指针被数据库拒绝；首次运行（script_only/full）在入队事务内创建/锁定唯一 active `ChapterAudio`——**唯一性由部分唯一索引 `UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL` 保证（R10/P0-4）**：两个并发首次创建仅一个成功（loser 按 SAVEPOINT 协议回滚重读），软删除恢复与索引冲突返回 409；双指针复合外键 `ON DELETE RESTRICT`（被当前指针引用的 run 行不可物理删除，R10/P1-1；R11/P2-2："任何 run 只墓碑化"由 repository/service 层强制策略承担，见验收 49/63）。
37. **派生执行事实 checkpoint（R9/P0-4，R10 分阶段冻结 P1-2）**：full 运行**分阶段冻结** `derived_execution_facts` 子项——剧本生成完成后冻结 `generated_script_facts`（+hash）、voice_binding 完成后冻结 `voice_resolution`（+hash）、scene_planning 完成后冻结 `scene_topology`（+hash），冻结过的子项不可覆盖（append-only）；恢复**从最后一个完整阶段的下一阶段继续**（不重跑已冻结阶段的非确定性剧本生成、不读实时值）；派生事实不参与 `input_signature`，由各子项 hash 单独校验并记录 `result_render_detail`；历史缺全部子项的 full 运行禁止恢复。
38. **历史产物回填（R9/P1-1，R10 明确落点 P1-1）**：有 `audio_path` 的历史章节回填 `published_run_id` + published `ChapterAudioOutput` + `published_provenance='legacy_unverified'`（可导出、不作为 CAS 发布基线）；**无法确认归属的产物回填到 synthetic migration run**（`run_type='migration_placeholder'`、`status='completed'`、`dispatch_status='cancelled'`、不可恢复/结算/重试/派发——复合外键合法成立，不出现"声称无法确认又建立强归属"）；历史 seed 产物 `render_status` 保持 null（不再回填精确 `rendered_all_seed`）；**`legacy_unverified` 进入 API schema（`published_provenance` 字段）**，消费者显式渲染"历史产物（未验证）"，不把未知 fallback/manual 历史误读为全 Seed 成功；全部历史 `ChapterAudioRun.chapter_audio_id` 按 `(audiobook_project_id, chapter_id)` 确定性回填（不留空）。
39. **dialogue 审批锁后重算（R9/P1-2，R10 全局锁序 P1-4）**：审批事务按固定顺序锁 `ChapterAudio` 行 + 三条 head（dialogue → director_override → voice_binding），锁后重算 `revision_set_hash` 与语义指纹再与 `base_revision_set_hash` 比对——并发编辑不会把新剧本误标 approved（TOCTOU 消除）；**编辑/审批/voice_binding/快照捕获全部遵守全局锁序 `Project → ChapterAudio → dialogue head → director head → voice head`**（R10/P1-4：普通编辑不再先锁 head 后写 ChapterAudio，编辑×审批交叉无死锁——真实 PostgreSQL 双事务并发测试覆盖）。
40. **billing_usage_ledger（R9/P1-3，R10 状态机 P1-3；R11 四态 P1-2）**：用量事实源——**供应商调用前**以稳定 `attempt_key` 写 `status='pending'` 记录，**成功返回后转 `status='succeeded'` 并补填 quantity/provider_request_id**（`quantity > 0` 由 CHECK 保证，**provider_request_id 可空**），**确定失败转 `confirmed_failed`（不结算）、无法判定转 `manual_reconciliation`（不自动结算，人工对账后转态）**；`UNIQUE (run_id, attempt_key)` 内部去重 + **`(run_id, provider, provider_request_id, usage_kind)` 部分唯一索引（provider_request_id 非空）**供应商侧去重；`pricing_key` 匹配多模型价格快照单价；供应商不返回 request id 时以 attempt_key 承担幂等；进程在"供应商成功、本地未落账"窗口崩溃 → 恢复后 pending 记录仍在，**按 provider 能力声明**：支持幂等/可查询的 provider 按 attempt_key 补录 succeeded——**用量不丢失、不产生第二笔费用**；**既不支持外部幂等又无法查询的 provider 转 manual_reconciliation 人工对账，不得自动重新调用（R11/P1-3）**；结算以 succeeded 记录 × billing_snapshot 为准；`segment_candidate` 不写。
41. **artifact 完整性增强（R9/P1-4）**：发布前置校验要求场景键集合全等 + 每场景恰一条 staged + 逐条校验 scene_topology_hash/segment_keys/content_digest/物理文件存在性/fallback source_kind 合同——缺漏或损坏不发布。
42. **voice_binding 并发锁（R9/P1-6）**：不同章节并发提交 voice_binding 时，同事务内 `Project` 行 FOR UPDATE 串行化双写，后提交者不覆盖前者，失败整体回滚。
43. **输出清理墓碑（R9/P2-3）**：清理只删物理文件并置 `file_status='purged'`/`purged_at`，登记与摘要保留可审计；被 published 镜像列引用的文件禁止清理；`file_status='missing'` 在幂等短路一致性检查与完整性校验中暴露。
44. **API schema 唯一化（R9/P1-5，R10 命名统一 P2-1；R11 值域收窄 P2-1）**：状态接口与 `SceneEditorDocument` 统一使用 `execution_status`（值域 {queued, running, paused, succeeded, failed, cancelled}，数据库 completed 投影 succeeded）、`published_render_status`（**值域 {rendered_all_seed, rendered_with_fallback, stale, null}，R11/P2-1**）、`desired_render_status`（**可含 manual_review_required/failed，R11/P2-1**）三维 + `published_provenance`——文档与接口不再出现"双维度"表述或 `render_status` API 字段名或 `execution_status=completed` 测试表述。
45. **事务所有权（R10/P0-3）**：`create_task`/`attach_celery_id`/`create_run`/`create_runs`/`enqueue_chapter_runs`/`_create_points_billing_event_log`/`_safe_record_audiobook_billing_freeze` 全部无内部 `db.commit()`（只 add/flush）；冻结后任意一步抛异常（含冻结事件日志写失败）→ 断言 task/run/desired_run_id/冻结事件全部无残留，未调用 `apply_async`。
46. **可靠派发（R10/P0-1）**：`apply_async` 明确失败 → 补偿且冻结释放幂等；**响应丢失（mock 抛超时异常但消息实际已入 broker）→ `dispatch_status='unknown'`、冻结不释放、run 不置 cancelled、进入对账**——不出现"已退款任务继续执行"；对账确认已投递后补记 `dispatched`；**worker 原子认领**：供应商调用前 CAS 认领（status→running + dispatch_status→dispatched），已取消 run（status=cancelled 或 dispatch_status=cancelled）认领失败立即终止、不调用供应商（mock 供应商断言零调用）。
47. **派发单位（R10/P0-2）**：多章节请求产生 N 条独立 Celery 消息 + N 个独立 `celery_task_id`（不再整批共用一个 signature/task id）；逐 run 派发失败互不影响（第 1 章 dispatched、第 2 章 cancelled 可同时存在）。
48. **唯一 active（R10/P0-4）**：真实 PostgreSQL 双事务并发首次创建同一章节 `ChapterAudio`——仅一个成功，loser 捕获 `IntegrityError` 后 `nested.rollback()` 重读复用（不抛 `InFailedSqlTransaction`）；部分唯一索引 `UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL` 生效；软删除恢复与既有 active 行冲突返回 409；迁移确定性去重后无重复 active。
49. **run 不可物理删除（R10/P1-1，R11 归因修正 P2-2）**：删除被 `desired_run_id`/`published_run_id` 引用的 run 行被数据库拒绝（ON DELETE RESTRICT）；**"任何 run 只墓碑化、永不物理删除"由 repository/service 层强制策略保证：无 `DELETE FROM chapter_audio_runs` 物理删除入口（全部改置 `deleted_at` 墓碑或禁止），终态 run 保留供审计/账单/回填**。
50. **synthetic migration run（R10/P1-1）**：无法确认归属的历史产物回填到 `migration_placeholder` run（复合外键成立）；该 run 不可恢复/不可结算/不可重试/不可派发；seed 历史 `render_status` 为 null + `published_provenance='legacy_unverified'`；API 返回 `published_provenance` 字段且消费者正确渲染"历史产物（未验证）"。
51. **分阶段 checkpoint（R10/P1-2）**：full 运行在剧本生成后（scene_planning 前）崩溃 → 恢复从 voice_binding 继续（重跑确定性音色解析，不重跑剧本生成）；voice_binding 后崩溃 → 从 scene_planning 继续；scene_topology 冻结后崩溃 → 从 scene_rendering 继续；各子项 hash 独立校验。
52. **ledger 崩溃窗口（R10/P1-3）**：模拟"供应商成功返回、进程在本地落账前崩溃"→ 恢复后 pending 记录存在（调用前已写），按 attempt_key 补录 succeeded，无重复入账、无丢失用量；`pricing_key` 参与结算单价匹配。
53. **全局锁序（R10/P1-4，R11 账户锁置顶 P0-2）**：真实 PostgreSQL 下编辑（dialogue）× 审批（dialogue-review）双事务交叉并发——统一锁序（ChapterAudio → dialogue head）下无死锁，任一事务正常完成；voice_binding 双写遵守 Project → ChapterAudio → head 顺序；冻结事务以 `pg_advisory_xact_lock(user_id)` 开头（锁序最前端）且与其他路径无交叉环。
54. **派发意图 outbox（R11/P0-1）**：run 创建事务内 `dispatch_status='pending'` + 固定 `celery_task_id` + `dispatch_attempts=0`/`next_dispatch_at=now()` 同事务落库；模拟"事务提交后、首次派发前进程退出"→ stale-pending 扫描器（dispatcher 租约认领）重放成功，消息入 broker，run 最终 `dispatched`；`dispatch_attempts` 超上限转 `unknown` 人工对账。
55. **账户级超额冻结防护（R11/P0-2）**：两个并发请求同时通过预检 → 冻结事务内 `pg_advisory_xact_lock(user_id)` 串行化，锁内重聚合余额 + 全部有效冻结，后到事务冻结总额超余额 → 整体回滚（或部分裁决），断言冻结总额不超过余额。
56. **任务-派发数据合同（R11/P0-3，R15/P1-2 修正子表列合同）**：父任务 + N 条 `audiobook_task_dispatches`（每 run 一条子派发记录，**子派发表无 `celery_task_id` 列**——`ChapterAudioRun.celery_task_id` 唯一，子派发表经 JOIN run 获取 `celery_task_id`）；N 个 worker 并发完成时父任务聚合为正确终态（全 succeeded→completed、部分失败→completed_with_partial_failure、任一 running→running、全 cancelled→cancelled）；暂停/恢复/取消按 run 级操作生效；`GET /tasks/{task_id}/status` 返回父聚合视图含 children 摘要；SSE 按 run 发出、前端按 job_id 聚合。
57. **worker 租约协议（R11/P1-1）**：worker CAS 认领后崩溃（未 ACK）→ `lease_expires_at` 到期后消息重投（`task_acks_late`/`task_reject_on_worker_lost`/`visibility_timeout` 配置生效）→ 新 worker 接管过期租约继续执行；claim_token 不匹配的续期被拒；先落库后 ACK。
58. **ledger 四态（R11/P1-2，R14/P0 统一命名）**：`pending → succeeded`（quantity>0，provider_request_id 可空，非空时部分唯一索引去重）；确定失败转 `confirmed_failed`（不结算）；无法判定转 `manual_reconciliation`（不自动结算，人工对账后转态）；"供应商不返回 request ID"的成功调用可合法转 succeeded（不再被 CHECK 拒绝）。
59. **provider 能力声明（R11/P1-3）**：声明"不支持外部幂等 + 不支持查询"的 provider 在"外部成功本地未落账"后转 `manual_reconciliation`，断言不自动重新调用（mock 供应商零二次调用）；支持查询的 provider 走自动补录。
60. **条件补偿（R11/P1-4）**：run A 派发失败时 desired 已被 run B 接管 → 条件更新 rowcount=0，不覆盖 `desired_run_id`，仅取消释放 run A；`predecessor_run_id` 为创建时持久化值（非动态推断）。
61. **canonical 去重（R11/P1-5）**：同组多行中较老行持有有效 audio_path/approved script/审核证据而最大 id 行无产物 → canonical 规则选有效产物行为保留行，产物/审核证据合并迁移到 canonical 行，物理文件不删除；迁移不调用物理删除逻辑（unlink）。**迁移执行合同（R19/P1-3，R20，R21）**：逐组短事务，事务 A（业务 + `completed` 标记同事务提交，提交后才可跳过）与事务 B（失败记录：回滚后独立短事务写 failed/脱敏 failure_detail/attempts/last_error_code，不随业务回滚消失，R21/P1-1；**事务 B 为 fail-closed 条件更新（`ON CONFLICT DO UPDATE ... WHERE status <> 'completed'`），绝不把已提交的 completed 覆盖为 failed；真实 PostgreSQL：事务 A 成功 commit → 模拟客户端在 commit 响应前断线 → 重试不得把 completed 改为 failed、不重复创建 synthetic run/output/文件登记且 attempts 不递增；attempts 仅确认失败时递增，R22/P1-2**）；重试先读进度表 completed 并重跑组级一致性校验再跳过（不依赖调用方本地状态）；迁移全局单实例 `pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)` 获取失败即退出（**会话锁用专用非池化连接持有、finally 解锁并关闭、不归还连接池；实例 A 获锁后异常退出 → finally 解锁/关闭连接 → 实例 B 随后成功获锁；实例 A 进程死亡 → 数据库断连自动释放 → 实例 B 可重新启动迁移；运维检查 SQL 定位长期持锁会话后人工确认才 terminate，R22/P1-3**），每组事务组级 advisory lock → progress FOR UPDATE → 锁后重查 status（**status 值域仅 pending/completed/failed，无 running/租约/接管分支，R22/P1-1**，R21/P1-2）；版本门禁证据（旧版本实例数为零或写入闸门日志，R20/P1-3）为 Migrate/Contract 准入；唯一索引创建前验证 SQL 全表无重复 active 组（R20/P1-2）；CONCURRENTLY 在 Alembic 事务外（或独立 revision `autocommit_block()`）执行且 `pg_index.indisvalid = true`；INVALID 索引清理前身份校验（schema/表名/`indisvalid=false`/`indisready`/`pg_get_indexdef` 定义一致，同名不同定义的有效索引停止 Contract；中断留 INVALID → 识别清理 → 重建 → `indisvalid=true` → indexdef 与预期一致，R21/P2-2）。
62. **published 值域收窄（R11/P2-1）**：`published_render_status ∈ {rendered_all_seed, rendered_with_fallback, stale, null}`（首次失败/人工评审不发布 → null）；`desired_render_status` 可含 `manual_review_required`/`failed`；`result_render_status` 为 Seed 四态；验收与测试表述不再称"Seed 五态"。
63. **run 不可删归因（R11/P2-2）**：repository/service 层无 `DELETE FROM chapter_audio_runs` 物理删除入口（全部改墓碑或禁止）；被指针引用的 run 删除被数据库拒绝；未被引用终态 run 的不可删由服务层策略保证。
64. **worker 首认领/过期接管拆分（R12/P0-1）**：worker CAS 认领后崩溃（未续期未 ACK）→ 租约过期 → 消息重投 → 新 worker 按"过期接管"CAS（`status='running' AND lease_expires_at < now()`）接管成功并继续执行，run 不再永久卡死 `running`；接管只换执行权、不回退运行态；接管分支对 cancelled run 拒绝。
65. **心跳与阻塞调用解耦（R12/P0-1）**：单次供应商请求最长超时 < `lease_interval`（断言请求超时配置小于租约）；或 heartbeat 独立于阻塞的供应商调用执行（mock 阻塞调用期间 heartbeat 仍能续期）；租约被接管后旧 worker 的续期被拒（claim_token 不匹配）且不再发起新供应商调用（mock 供应商零新调用）。
66. **celery_task_id cutover（R12/P0-2）**：真实 PostgreSQL 迁移——"多 run 共用旧 Celery ID + null ID + 旧活动任务"三类数据：分类 → parent/child 回填（`legacy-` 前缀唯一 id）→ null 回填 → 旧活动任务 drain/cancel → 施加 `NOT NULL` + `UNIQUE`；断言迁移成功、约束生效、`legacy-` 前缀 run 的查询/暂停/恢复/SSE 走展示投影（按子派发表定位，不做 broker 关联）。
67. **账户锁收敛（R12/P0-3）**：共享 points mutation service 下，拆书/小说协同/短剧冻结/管理员调账与有声书冻结并发时同一 advisory 锁键串行化——断言任意交错下冻结总额 ≤ 余额；未收敛路径（直接调用旧冻结入口绕过 service）的穿透测试暴露超额冻结并拒绝。
68. **派发单一事实源与终态矩阵（R13/P0-a + P1-a 修正，R15/P0-1/P1-1 补值域与优先级）**：子派发表无 celery_task_id 列（查 JOIN run，R13/P1-d）；复合外键拒绝 `chapter_audio_id` 不属于该 run 的子派发插入；父聚合前先执行 `normalize_run_status` SQL CASE 投影（pending/queued→queued、completed→succeeded、**expired→cancelled（R15/P0-1）**、canceled/cancelled→cancelled），再基于规范化值做互斥矩阵，断言分支不并列命中且 `completed_with_partial_failure` 写入父表成功（VARCHAR(32) + CHECK 放行）；**unknown 置顶（R15/P1-1）**：`{unknown, failed}`/`{unknown, running}`/`{unknown, succeeded}` 三组合均先命中 fail-closed 分支（父 failed + `aggregation_unknown_status`），不产出 `completed_with_partial_failure`；**计数穷尽矩阵（R17/P1-2）**：按 §1.1 正式矩阵六分支（①任一 unknown fail-closed → ②任一进行中 → ③全 succeeded → ④全 cancelled → ⑤至少一 succeeded 且存在失败/取消 → ⑥无 succeeded 且至少一 failed）断言组合**穷尽且互斥**——`{cancelled, failed}` → `failed`（命中⑥，R17/P1-2 修复悬空组合）、`{cancelled, failed, succeeded}` → `completed_with_partial_failure`（命中⑤）、`{failed, failed}` → `failed`（命中⑥）、全 cancelled → `cancelled`（命中④）、全 succeeded → `completed`（命中③）、任一 running 组合 → `running`（命中②）、含 unknown 组合 → fail-closed（命中①）——每一组合恰命中一条分支，不悬空、不并列；`job_id` = `task:{AudiobookTask.id}` 命名空间字符串；`GET /tasks/{task_id}` 按 `task:{id}` 与 `celery_task_id`（兼容期）分别解析；SSE 事件携带 `run_id` + 父 `job_id`。
69. **ledger 结算封口（R13/P1-b strict barrier，R14/P1-e 幂等数据合同，R15/P0-2 索引修正，R17/P0 统一 finalizer）**：run 存在 `pending`/未收敛 `manual_reconciliation` 时结算被拒、冻结保留（断言不写入 settle 事件）；收敛后由统一 finalizer 执行唯一一次最终 settle（R17/P0：任何路径不得绕过 finalizer 直接 settle——run 未终态时人工收敛只提交 ledger 与审计，幂等域 = run 级 billing_key：账户锁内"已 settle"短路 + `admin_operation_logs` 部分唯一索引数据库兜底——`resource_id` 账户作用域 + `dedupe_superseded` 谓词排除，R15/P0-2；复合串 `{billing_key}:settle:{run_id}` 仅作 `request_params.settle_scope` 审计描述、作为 billing_key 传入被拒绝），不引入 supplement。
70. **恢复证据持久化（R13/P0-b 证据字段落地）**：断言 `encrypted_result_url`/`result_url_expires_at`/`capability_snapshot_json` 随状态机写入；恢复四种证据组合（有 `provider_request_id`→query；有 `encrypted_result_url`→拉取；确认幂等键→replay；无证据→manual_reconciliation 零二次调用）；修改能力表配置后重放历史调用仍按 `capability_snapshot_json` 快照决策。
71. **run 墓碑与级联（R12/P1-4）**：`ChapterAudioRun` 有 `deleted_at`；project/chapter/output/artifact 外键全部 `ON DELETE RESTRICT`——硬删项目被数据库拒绝；项目删除仅软删除（置 `deleted_at`），软删除后 run 行保留（billing/审计引用仍成立）。
72. **dispatched 未认领重投（R12/P1-5）**：`apply_async` 成功（`dispatch_status='dispatched'`、`dispatched_at` 写入）但 worker 从未认领 → 超 `first_claim_deadline` 后 dispatcher 按"`dispatched` && `claim_token IS NULL` && 超时"CAS 重投（复用固定 celery_task_id）→ run 最终被认领执行；broker 实际仍存旧消息时无重复供应商调用。
73. **ledger DDL 可执行性与值域（R14/P0）**：真实 PostgreSQL 建表/Alembic 迁移——`uq_billing_usage_ledger_dedup` 部分唯一索引引用 `provider_request_id`（列存在，建表与迁移成功，旧名 `request_id` 无残留）；`status` 为 String(32)，`manual_reconciliation`（21 字符）合法写入且 CHECK 放行；`(run_id, provider, provider_request_id, usage_kind)` 去重语义不变（NULL 不参与）。
74. **父 CHECK 两阶段收窄（R14/P1-b）**：阶段 1.1 迁移后（宽 CHECK 含 `pause_requested`/`paused`）旧 API 暂停请求（`routes_tasks.py` 约 86 行）与旧 worker 写 `paused`（`job_tracker.py` 约 395 行）均成功；部署新代码 + drain/cancel 旧 worker + 清洗父表遗留暂停态并重新聚合后收窄 CHECK——收窄后父任务写暂停态被数据库拒绝（父任务只允许聚合值），run 级暂停不受影响。
75. **normalize fail-closed（R14/P1-c）**：合法 `pause_requested` run 规范化后父任务投影 `running`（矩阵②命中，非 unknown）；历史遗留未知值（如 'weird'）→ 父任务投影 `failed` + `detail_json` 审计错误 `aggregation_unknown_status`（断言非无分支返回、非静默丢弃）；迁移前清洗后新写入无未知值（run 状态 CHECK 生效）。
76. **dispatcher 结果回写 token fencing（R14/P1-d）**：真实 PostgreSQL 双 dispatcher 并发——A 认领（token A）后阻塞、claim 过期、B 以 token B 接管并成功投递；A 迟到返回"明确失败" → A 的补偿（取消/释放冻结/desired 回退）被 token CAS 拒绝（rowcount=0），B 的 claim 与投递结果保持（run 不被取消、冻结不释放、desired_run_id 不变）；A 迟到返回"成功"同样不清除 B 的 claim。
77. **settle 幂等数据合同（R14/P1-e，R15/P0-2 索引作用域与清洗修正）**：`record_points_billing_settle` 传原 run 级 billing_key 结算成功；把复合串 `{billing_key}:settle:{run_id}` 当 billing_key 传入被拒绝（无 active freeze）；`admin_operation_logs` 部分唯一索引拒绝同**账户**（`resource_id`）同 billing_key 第二条 settle 事件——不同 actor（user_id 不同）对同一 target 账户同样被拒（user_id 语义不可作为不变量依赖）；历史重复 settle 置 `dedupe_superseded=true` 后索引建成、事件流聚合忽略（余额不重复扣减）；两个并发最终 settle 事务（真实 PostgreSQL）只产生一条 settle 事件、一次积分扣减。
78. **run 状态值域含 expired（R15/P0-1）**：真实 PostgreSQL 迁移后——候选片段被顶替（`segment_candidate_registry.py` 约 152 行）与临时片段过期清理（`temp_segment_janitor.py` 约 149 行）仍可合法写 `expired`（CHECK 放行）；活动检查 cancelled/canceled/expired 集合（`background_jobs_shared.py` 约 128 行）行为不变；历史 `completed` run 保持数据库值、聚合投影为 succeeded（清洗不改写为投影值）。
79. **settle 索引账户作用域与清洗（R15/P0-2）**：真实 PostgreSQL——`UNIQUE (resource_id, (request_params->>'billing_key')) WHERE operation_type='POINTS_BILLING_SETTLE' AND COALESCE(request_params->>'dedupe_superseded','false') <> 'true'` 建表成功：①同账户同 billing_key 第二条 settle 被拒；②不同 actor（user_id 不同）对同一 target 账户第二条 settle 同样被拒；③预置重复历史行（最新一条不置位、其余 `dedupe_superseded=true`）后索引创建成功，且事件流聚合过滤标记行（余额/冻结重算与"已 settle"短路均忽略）。
80. **manual_reconciliation 人工收敛写路径（R15/P1-4，R16/P0 + P1-1 强化）**：非管理员调用收敛入口 403；reason/evidence 缺失被拒；`target_status='succeeded'` 缺 `quantity` 或 quantity≤0 被拒（422，CHECK 前校验）；**初始 `quantity=NULL` 的 manual_reconciliation ledger 经人工确认（quantity>0 + snapshot 匹配校验通过）合法转为 succeeded——真实 PostgreSQL 断言 CHECK `ck_billing_usage_ledger_succeeded_fields` 放行（R16/P0）**；`usage_kind`/`unit`/`pricing_key` 与 run 不可变 `billing_snapshot` 不匹配时收敛被拒（422）；同一 ledger 连续两次收敛——第二次 CAS rowcount=0 返回 409；两个管理员并发收敛同一 ledger 仅一个成功；**故障注入：CAS 成功后 settle 前抛异常 → CAS 与审计一并回滚、ledger 回到 manual_reconciliation、冻结保留、再次请求成功（R16/P1-1）；settle 写入失败重试后最终只产生一条 settle 事件并释放冻结（R16/P1-1）**；收敛后锁内 strict barrier + 最终 settle 成功（未收敛保持冻结）；`ledger_reconciliation_audits` 记录完整（from/to/operator/reason/evidence/**confirmed_quantity**/reconciled_at 全量断言，succeeded 时 confirmed_quantity 与 ledger.quantity 一致）；**证据单调（R17/P1-1）**：原 `commit_stage='result_persisted'` 收敛不倒退（new_commit_stage='result_persisted'）、原 `pre_call` 收敛 succeeded 推进为 `post_call`；原已有 `provider_request_id` 时传入不同值被拒（409/422，断言原值未被覆盖）、传入相同值或空值放行、NULL 补齐成功；审计断言 `previous_provider_request_id`/`new_provider_request_id`/`previous_commit_stage`/`new_commit_stage`/`recovery_method='manual'` 结构化字段全量写入且单调 CHECK 放行（**rank 编码 pre_call=1 < post_call=2 < result_persisted=3 单调不减——原记录已 result_persisted 收敛 succeeded 时 new_commit_stage='result_persisted' 通过 CHECK，R18/P1-1 修正 R17 硬编码 post_call 撞 CHECK**）；**finalizer 联动（R17/P0）**：run 未执行终态 → 收敛只提交 ledger+audit（不 settle、不置封口）；run 已执行终态 + 无有效 lease + barrier 通过 → 同事务置 `billing_finalized_at` + 唯一 settle。**预读仅路由（R21/P2-3）**：无锁预读值仅用于确定锁键与路由，不得参与任何安全判断（ledger 状态/quantity/provider_request_id 是否为空/run 是否终态/finalizer 准入/previous/new 审计字段一律锁后重做）；取锁后重新读取并逐项校验——ledger.id 仍存在、`ledger.run_id` 与预读一致、`run.billing_account_user_id` 与预读锁键一致、`ledger.status='manual_reconciliation'`、`run.billing_finalized_at IS NULL`（任一不一致 → 409/422 拒绝），且 `ledger.run_id` 不可变性落为数据库约束或 repository 禁止更新入口。
81. **前端 StageStatus 穷举映射完备（R15/P1-3）**：`types.ts` 新增 `'cancelled'`/`'completed_with_partial_failure'` 后 tsc 编译通过——`STAGE_STATUS_LABELS`（constants.ts 约 56 行）、`STAGE_STATUS_COLORS`（TaskStageDetails.tsx 约 23 行）、`audiobookTheme.taskStatus`（约 83 行）均含两新键；父任务聚合视图渲染部分失败状态不崩。
82. **ledger_reconciliation_audits 不可变审计（R16/P2-1）**：真实 PostgreSQL 建表/Alembic 迁移——显式主键、`ledger_id` NOT NULL + ON DELETE RESTRICT（被审计 ledger 物理删除被数据库拒绝）、`from_status` CHECK 恒 `manual_reconciliation`、`to_status` CHECK ∈ {succeeded, confirmed_failed}、operator_user_id/operator_username/reason/evidence/reconciled_at 全部非空、reconciled_at 数据库端默认 now() 且带时区；`to_status='succeeded'` 且 `confirmed_quantity` 为空/≤0 被 CHECK 拒绝、`confirmed_failed` 且 `confirmed_quantity` 非空被拒绝；**append-only 合同（R16/P2-1；R19/P2-2 数据库级强制）**——repository/service 层无 update/delete 入口，且 BEFORE UPDATE OR DELETE trigger（`trg_ledger_reconciliation_audits_append_only` → RAISE EXCEPTION）或对应用角色仅授 SELECT/INSERT——**测试直接执行 SQL 断言数据库拒绝 UPDATE/DELETE**（不只是验证当前 service 无入口），审计记录插入后无法被任何应用路径或直连 SQL 修改/删除。
83. **run 计费封口与结算并发（R17/P0）**：真实 PostgreSQL 双会话——会话 A 人工收敛 finalizer（run 已执行终态 + 无有效 lease）与会话 B worker 新建下一条 `pending` ledger 并发：**断言不可能出现"settle 在先、ledger 在后"**——若 settle 已提交则 `run.billing_finalized_at` 必已置位、B 的建账 CAS（`AND billing_finalized_at IS NULL`）rowcount=0 被拒；若 B 先建账则 finalizer strict barrier 不通过、不 settle（冻结保留）；**worker 认领/过期接管两分支 CAS 均含 `billing_finalized_at IS NULL`**——已封口 run 的认领、接管与新建 ledger 全部被拒（mock 供应商零调用）；finalizer 与 worker 建账以 run 行 FOR UPDATE 串行化；**锁序统一（R19/P0，R20/P1-1 纳入 ledger 行，R21/P2-1 精确化：三层锁序 + 锁内写入顺序）**：worker 终态主路径、人工收敛路径、finalizer/beat 扫描器全部使用完全相同的三层锁序“账户 advisory 锁 → run 行 FOR UPDATE → ledger 行 FOR UPDATE（多条按 `ledger.id` 升序）”（加锁仅这三层；持锁后按锁内写入顺序执行：ledger 状态更新 → 必要时插入 `LedgerReconciliationAudit` → strict barrier → 置 `billing_finalized_at` 封口 → settle 事件写入；**audit 仅用于人工收敛路径，worker 成功转态/confirmed_failed 自动关账/纯 finalizer 重试不插入 reconciliation audit，且 audit INSERT 不是锁层级，R21/P2-1**；完整合同见 §2.9；worker 终态事务先取账户锁、取锁后重新校验 status/token/封口，§2.1 执行终态写协议；禁止任何路径先取 run 锁后取账户锁，禁止在账户锁与 run 锁之前按 ledger_id 查询或 FOR UPDATE ledger）——真实 PostgreSQL 双会话：会话 A worker 终态主路径 × 会话 B 人工收敛（同账户）并发交错，断言无死锁且两路径加锁顺序完全相同（R18 原文“终态 CAS 先锁 run、finalizer 后取账户锁”与该验收声明的固定锁序矛盾，构成确定死锁环，R19/P0 修复）；**worker 终态关账 × 人工收敛同一 ledger（R20/P1-1）**：会话 A worker 终态事务按证据关账 pending ledger X × 会话 B 人工收敛同一 ledger X 并发交错，断言两路径均按统一三层锁序推进、无死锁且仅一方成功修改该 ledger（另一方 CAS rowcount=0 或锁后重校验失败回滚/409，不产生双写），并代码级检查收敛入口实现不在账户锁/run 锁前对 ledger 加锁、无锁预读值仅用于锁键路由未参与任何状态/证据判断（全部锁后重做，R21/P2-3）；`billing_finalized_at` 一次性置位不可回退（重复 finalizer 幂等短路，不产生二次 settle）；人工收敛 run 未终态只提交 ledger+audit，worker 后续新增 ledger 正常，run 结束后统一 finalizer 一次结算。**finalizer 主路径（R18/P0，修复 R17“只测并发不测主路径”）**：①**正常成功当场结算**——worker 终态事务按统一锁序执行：先取账户锁 → run 行 FOR UPDATE → 取锁后重校验（status/claim_token/封口，不用锁前读取结果）→ 终态 CAS 清租约（`claim_token/claimed_at/lease_expires_at=NULL`）→ 按证据关账 → 同事务 finalizer 结算 → settle 成功、冻结释放、`billing_finalized_at` 置位（主路径断言，不依赖人工收敛入口；取锁后重校验失败——租约已被接管/run 已取消/已封口 → 回滚终止不写终态，R19/P0）；②**取消后无 pending**——写 cancelled/failed 后本 run 全部 pending 已按证据关账（`pre_call` 无供应商证据 → `confirmed_failed`；已发出/结果不明 → `manual_reconciliation`），全部 confirmed_failed 时 barrier 通过 → 当场 settle，冻结不挂死；③**租约未清时 finalizer 拒绝且清租约后重试成功**——run 终态但 lease 未过期时 finalizer 前置拒绝；租约自然过期后 beat 扫描器（`billing_finalizer_scan`：`执行终态 ∧ billing_finalized_at IS NULL ∧ 无有效租约`）重试 finalizer 成功；④**建账谓词三要素**——`status='running' AND claim_token=:token AND billing_finalized_at IS NULL` 任一不满足拒绝建账（非 run 持有者 token 建账被拒，不得只查封口字段）。
84. **计费账户权威来源（R17/P1-3）**：创建 run 与冻结同一事务写入 `billing_account_user_id`（= 冻结 `target_user_id`）且 `run_input_snapshot.billing_context.billing_account_user_id` 与之一致；**冻结后项目所有者变化（真实 PostgreSQL：`Project.user_id` 改指他人）→ 人工收敛锁键与最终 settle 仍按原 `billing_account_user_id` 账户执行，active freeze 的 `resource_id`/`billing_key`/`run_id` 校验全部一致通过、积分扣减落在原账户**；freeze 的 `resource_id`/`billing_key`/`run_id` 任一与 run 不一致 → 收敛被拒（422）；`billing_account_user_id` 为 NULL 的历史 run 禁止人工收敛与结算。**不可变数据库约束（R18/P2）**：`billing_finalized_at` 非空后任何 UPDATE 修改/清空被 trigger 拒绝（一次性置位不可回退）；`billing_account_user_id` 非空后修改被 trigger 拒绝（NULL → 值回填放行）；repository 层无这两列 update 入口（测试锁定）。
85. **succeeded 可结算性约束（R17/P1-4）**：worker 自动 `pending → succeeded` 与人工收敛共用**统一 ledger transition service** 的可定价性校验——`pricing_key` 不存在于 `billing_snapshot.prices`、`unit` 不一致、`billing_snapshot_id` 无效或 `quantity <= 0` 均不得转 succeeded（自动路径转 `manual_reconciliation`、人工收敛 422）；真实 PostgreSQL 断言收紧后 CHECK `ck_billing_usage_ledger_succeeded_fields`（`quantity > 0 AND pricing_key IS NOT NULL AND billing_snapshot_id IS NOT NULL`）与 `ck_billing_usage_ledger_unit`（`unit IN ('second','char')`）生效——缺 pricing_key/billing_snapshot_id 或 unit 非值域的 succeeded 写入被数据库拒绝；迁移扫描历史 succeeded 缺定价事实记录：可从 `run_input_snapshot` 确定性恢复 → 回填后放行，不可恢复 → 置 `manual_reconciliation`（显式 `legacy_unverified` 语义，拒绝自动结算，不以 NULL 静默放行）。**pricing_key 映射（R18/P1-3）**：`usage_kind → pricing_key → prices 键 → unit` 映射为可结算性验证唯一依据（`seed_render→seed_scene→second`、`tts_chars→tts→char`、`asr_seconds→asr→second`、`remix→remix→second`）——**remix 用量能经 transition service 验证自动转 succeeded**（`billing_snapshot.prices` 含 `remix` 条目，不全部掉进人工对账）；unit 与 `prices[pricing_key].unit` 不一致拒绝转态。**unit 合同（R19/P1-1）**：`prices[*].unit` 为计量单位（值域与 `ck_billing_usage_ledger_unit` 完全一致：`second|char`），币种由价格字段名表达（`price_per_second_yuan`/`price_per_char_yuan`）——R18 示例 `"yuan/second"`/`"yuan/char"` 属单位合同错误（按之实现，全部正常自动 pending→succeeded 会被“unit 与 ledger.unit 一致”校验拒绝并进入 manual_reconciliation）；`usage_kind → pricing_key → unit` 映射与 unit 值域定义为后端唯一常量表，快照生成、统一 ledger transition service、人工收敛校验与测试共用同一来源（测试断言四处同源、无重复硬编码）。

## 7. 测试计划

### 后端（TDD）

- `project_audio_config` 引擎分支：读写 `engines.{mode}.tts_models.{model}.characters`/`audio_fx`/`scene_generation_preferences` 落对应分支；旧顶层 `tts_models`/`characters`/`audio_fx`/seed 键读取归一化与迁移映射（仅 legacy_stems / seed_scene 各自回退）；读写优先级表逐级验证（含 `_LEGACY_MODEL_KEYS` 映射）；顶层镜像仅 legacy_stems+默认模型。
- **Alembic 迁移**：空库迁移 + 含历史数据库迁移；历史行**一次性**回填 `engine_mode` 与快照（含 `engine_config_fingerprint`，断言无"先全量 legacy 回填"中间步骤）；NOT NULL/CHECK（含 `frozen → 快照非空`、**`snapshot_status ∈ {frozen, legacy_unfrozen, legacy_unverified}` 三态值域 CHECK——R8**）/组合索引/部分唯一索引生效断言；legacy_unfrozen / legacy_unverified 批次恢复被拒；**snapshot_status 四步迁移顺序断言（R19/P2-1）**：可空列无默认 → 按证据回填 → 非法组合校验 → NOT NULL + CHECK，且应用服务创建批次显式写 `snapshot_status`（无 server_default，不带 status 的裸插入失败）。
- `resolve_engine_mode`：`auto` 在存在/不存在 `engines.seed_scene` 分支或旧 seed 键时分别归一化；非法值回退默认。
- **快照与运行输入**：`build_engine_config_snapshot`/`build_run_input_snapshot` 构造与解析；`engine_config_fingerprint` 不包含 `captured_at`/`source_audio_config_hash`，**但包含 `seed_audio_model` 与 `providers` 组合**（模型/供应商不同 fingerprint 不同，`seed-audio-1.0` 与 `seed-audio-1.0-multilingual` 不复用）；`run_input_snapshot` 为方案 A 自包含正文（engine_config_payload/script_facts 正文/voice_resolution 正文/revision_projection 正文/run_options/billing_context + input_signature），**按 run_type 合同断言**（audio_from_scripts/重渲染快照含 `script_facts` 正文与 revision 投影；full/script_only 快照 `script_facts` 为 null 且含 `source_chapter_content` 正文；创建运行事务内读一次即冻结）；**签名断言（R8）**：`input_signature = sha256(canonical_json(signed_payload))`——signed_payload 含全部业务输入与计价事实、排除 `input_signature` 自身与纯审计字段（captured_at/snapshot_id/billing_rules_version），相同输入相同签名；**checkpoint 派生事实断言（R8，R9 升级为 derived_execution_facts，R10 分阶段 P1-2）**：full 运行**分阶段冻结** `derived_execution_facts` 子项——剧本生成完成后冻结 `generated_script_facts`（+ `generated_script_facts_hash`）、voice_binding 完成后冻结 `voice_resolution`（+ `voice_resolution_hash`）、scene_planning 完成后冻结 `scene_topology`（+ `scene_topology_hash`），冻结过的子项不可覆盖（append-only）；恢复从最后一个完整阶段的下一阶段继续（不重跑已冻结阶段的非确定性剧本生成、不读 script_json/audio_config 实时值）；各子项 hash 失配报错并记录 `result_render_detail`，历史缺全部子项的 full 运行恢复被拒；**计费断言（R8）**：`billing_context.billing_snapshot` 内嵌单价/`user_price_basis`/`user_price_rate`/`provider_discount_capture_rate`/`provider_discount_rate`/`provider_discount_source`/`points_per_yuan`/`freeze_buffer_rate`/`margin_warning_rate`/`negative_margin_block_enabled`/`settlement_formula_version`（对齐实际计费模型字段），修改定价策略后预检与结算结果不变；**六步顺序断言（R9，R10 事务所有权 + 可靠派发）**：捕获（每 run 独立）→ 预检（snapshot + 实时余额）→ 同一事务建 run + 快照 + desired_run_id + **同事务冻结**（冻结失败整体回滚；**R10/P0-3：`create_task`/`attach_celery_id`/`create_run`/`create_runs`/`enqueue_chapter_runs`/`_create_points_billing_event_log`/`_safe_record_audiobook_billing_freeze` 全部无内部 commit、只 add/flush，冻结后任一步异常无 task/run/指针/冻结事件残留**）→ **事务提交后派发由 dispatcher 兜底**（R11/P0-1：run 即 outbox——`dispatch_status='pending'` + 固定 `celery_task_id` + `next_dispatch_at` 同事务落库，stale-pending 扫描器 CAS 租约认领重放，`dispatch_attempts` 超上限转 unknown；R10/P0-2：每 run 独立消息 + 独立 task id；**三态：明确失败→条件补偿（锁定 ChapterAudio + `UPDATE ... SET desired_run_id = :predecessor_run_id WHERE id = :chapter_audio_id AND desired_run_id = :failed_run_id`，rowcount=0 不覆盖新指针，R11/P1-4；释放冻结/run cancelled/`dispatch_status='cancelled'`）；结果未知→`dispatch_status='unknown'` 不释放冻结、不置 cancelled、走对账；成功→dispatched**；worker 供应商调用前原子认领，rowcount=0 零供应商调用；**R11/P0-2：冻结事务开头 `pg_advisory_xact_lock(user_id)`，锁内重聚合余额 + 全部有效冻结统一裁决**）→ 结算；**billing_usage_ledger 断言（R9/P1-3，R10 状态机 P1-3）**：供应商调用前以 `attempt_key` 写 `status='pending'`，成功返回后同一条转 `succeeded` 补 quantity/provider_request_id（CHECK 保证 quantity > 0）、失败不转；同 run 同 attempt_key 重复写被唯一约束拒绝（重试幂等）；同 run 同 provider 同 request 同 usage_kind 重复 succeeded 被去重约束拒绝；恢复续跑命中 pending 记录按 attempt_key 补录 succeeded（不重写、不产生第二笔费用）；`pricing_key` 参与结算单价匹配；**run 级 billing key 断言（R8，R9 命名）**：`audiobook:{audiobook_project_id}:run:{run_id}` 幂等；**恢复仅消费快照正文重建输入**（修改 `audio_config` 与 `script_json` 后恢复结果不变）；后台/计费/恢复/片段重新生成消费快照不读实时配置（任务入队后修改 `audio_config` 不影响执行输入）；`voice_mapping` 不再被写入。
- **批次复用**：engine_mode + engine_config_fingerprint 一致复用；任一不一致新建（含 seed_audio_model/provider 组合不同）；两阶段流程切换引擎后新批次复制已审批剧本——**复制合同断言（R7）**：`script_json` 正文 + `script_status='approved'` + 源 script hash + `script_review_json` 审核证据 + `source_audiobook_project_id`/`source_chapter_audio_id` 审计引用 + **`source_script_hash`/`source_script_review_version`/`source_provenance_json` 持久化字段与合同一一对应**，新批次可无阻碍执行 `audio_from_scripts`。
- `ChapterAudioRun` 列：`engine_mode_snapshot`、**`chapter_audio_id`（R9/P0-3：不可变，创建时写入；复合唯一键 `(id, chapter_audio_id)` 生效）**、`run_input_snapshot`、`revision_set_hash`、`input_signature`、**`dispatch_status`（R10/P0-1：非空默认 `pending`，值域 CHECK `{pending, dispatched, cancelled, unknown}`；入队写 pending、派发三态流转、synthetic migration run 置 cancelled；worker 认领 CAS 后置 dispatched）**、**`result_render_status`/`result_render_detail`（R8：运行结束即写，无论是否发布；R9：值域按引擎断言——Seed 四态 / legacy 二态，R11/P2-1 不再称五态）** 写入与读取；`ChapterAudio` 双指针列（**复合外键 `(desired_run_id, id) → runs(id, chapter_audio_id)` / `(published_run_id, id) → runs(id, chapter_audio_id)`，R9**）与 **`ChapterAudioOutput`（R7/R8 完整模型，R9 增 `file_status`/`purged_at` 墓碑）**：入队仅更新 `desired_run_id`；完成时**幂等完整发布事务（R8，§2.4 规则 4 八步；R9 修订）**——**锁行 → 幂等短路（published_run_id+签名相同，先经 R9 最低一致性检查：published 登记存在 + 镜像列齐全 + 物理文件存在，损坏不短路）→ 前置校验（run 归属/终态/**发布谓词按引擎**：seed `rendered_all_seed`/`rendered_with_fallback`、legacy 系 `completed`+整章输出齐全/staged 恰一条/**artifact 完整性增强**：场景键全等+每场景恰一条+拓扑/锚点/digest/文件存在性/fallback 合同）→ CAS 含 `id`（`WHERE id = :chapter_audio_id AND desired_run_id = :run_id`，rowcount=0 立即结束）→ 旧输出 supersede 排除 `run_id <> :run_id` → staged→published → artifact 以 `chapter_audio_id` 为作用域切换 → 单事务提交**——旧 run 晚完成不覆盖、新 run 失败不破坏旧产物；**幂等重试断言（R8）**：完成回调重复触发不二次 supersede、不报错；**损坏不短路断言（R9/P2-1）**：published 登记/镜像列/物理文件任一缺失时重复回调报错并走修复流程，不静默成功；**输出路径断言含 run_id 段**，两个 run 的输出文件互不覆盖；**seed 失败态（failed/manual_review_required）与 legacy `failed` 不触发发布事务，旧已发布产物与镜像列均不变**；**legacy 系（full/audio_from_scripts/chapter_remix）`result_render_status='completed'` 可发布（R9/P0-2）**；staged 输出不可被下载/试听链访问。
- 计费预检：`resolve_audiobook_billing_pricing_context` 在冻结/未冻结批次下分别从快照/拒绝读取。
- **SceneEditRevision 双表（R7）**：insert（append-only）+ head 表 UPDATE（仅 `head_revision_id`，hash 经 JOIN 校验一致）；`revision_hash` 唯一约束生效；同名 revision_hash 重复 insert 被拒；**复合外键作用域断言**：head 指向跨章节/跨 edit_type revision 的 insert 被数据库拒绝，parent 跨作用域同样被拒；并发控制：两个并行请求中仅一个成功创建 head 行（`(project, chapter, edit_type)` 唯一约束），另一个捕获 `IntegrityError` 后重读 head。
- **原子并发与幂等闭环（R7/R8，R9 SAVEPOINT 精确写法）**：带过期 `base_revision_hash` 的 insert → `409`（验证 head 表行锁生效 + 比对逻辑）；**幂等短路**：候选 hash 以请求 `base_revision_hash` 为 parent 计算——同 base 同内容重复提交（网络重试、并发双端、loser 重读 head 后）返回原 revision 不插入（**重试不误判 409**）；head 被推进后重试原请求 → 409（客户端按新 base 刷新）；**SAVEPOINT 并发协议（R8，R9 精确写法）**：真实 PostgreSQL 双事务并发测试（两会话同 base 同时提交）——loser 捕获 `IntegrityError` 后对 `nested = session.begin_nested()` 调用 `nested.rollback()`（**严禁 `session.rollback()`，断言不抛 `PendingRollbackError`**）再重读 head，断言不抛 `InFailedSqlTransaction` 且按候选 hash 返回幂等成功或 409（而非仅模拟 IntegrityError）。
- `SceneEditorDocument` 聚合：合并 script_json + checkpoint + SceneEditRevision 链 + SceneAudioArtifact。
- `scene_audio_artifacts`：登记（`status='staged'` + **`chapter_audio_id`（R8）**）+ `content_digest` 校验；**部分唯一索引 `UNIQUE (run_id, scene_id) WHERE deleted_at IS NULL`** 防重复登记（同 run 同 scene 重试 insert 被拒；superseded 后同 run 同 scene 可重新登记）；**复合外键作用域断言（R8，R9 收紧）**：artifact 的 `(run_id, chapter_audio_id)` 与所属 run 不一致（含跨 chapter_audio）时 insert 被数据库拒绝；**状态机断言（R7/R8）**：发布事务前 staged 不可经普通 stream 端点访问，发布后 active 可访问，被替代后 superseded 不可访问而 audit-stream 可访问；**发布作用域断言（R8）**：发布 run A 仅 supersede 同 `chapter_audio_id` 下其他 run 的 active artifact，其他批次/引擎同源章节的 artifact 保持 active。
- **旧脚本接口拒绝**：`PUT /script` 对 seed_scene 批次返回 409/400；legacy_stems 批次保持现有行为不变。
- **dialogue 审批接口（R8）**：编辑 → pending；`POST .../dialogue-review` verdict=reviewed → pending→reviewed、再 approved → reviewed→approved；一次性直批（reviewed+approved 同次提交）pending→approved；`base_revision_set_hash` 失配返回 409（审批期间有新编辑）；审核证据写 `script_review_json` + `script_review_version`；approved 后可创建 `audio_from_scripts` run；审批后再次编辑重置 pending 并清空审核证据；legacy_stems 批次调用返回 400/409。
- **三维投影（R8，R9 API 值域唯一化）**：首次 manual_review_required 未发布时 `published_render_status=null`、`desired_render_status=manual_review_required`、`execution_status=succeeded`（数据库 completed 投影 succeeded，API 值域 {queued, running, paused, succeeded, failed, cancelled}）；重渲染失败后 `desired_render_status=failed` 而 `published_render_status` 保持旧值；`SceneEditorDocument` 同时携带三维（字段名 `published_render_status`/`desired_render_status`/`execution_status`，无 `render_status` API 字段）。
- **run 级输出清理（R8）**：superseded 输出与整章文件超 30 天回收；staged 且 run 终态超 30 天回收；published 输出不清理；`chapter_audio_outputs` run_id 唯一约束与配额上限生效。
- **全量资源标识校验**：所有场景编辑端点 `audiobook_project_id` 校验 + 章节从属校验 + 资源隔离（同一 audiobook_project 不可访问另一源 project 的章节）。
- **冻结-派发闭环（R9/P0-1，R10 可靠派发）**：冻结失败（余额不足/快照不可用）断言 run/指针/快照一并回滚、无 run 残留、无冻结记录、未调用 `apply_async`；**R10 事务所有权（P0-3）**：`create_task`/`attach_celery_id`/`create_run`/`create_runs`/`enqueue_chapter_runs`/`_create_points_billing_event_log` 全部无内部 `db.commit()`（同事务内 `desired_run_id` 与 run 行同时可见/同时消失），冻结后任一步异常（含冻结事件日志写失败）断言 task/run/desired_run_id/冻结事件全部无残留；**逐 run 派发（P0-2）**：N 章产生 N 条独立消息与 N 个独立 `celery_task_id`；派发明确失败（broker 异常 mock）断言冻结释放（幂等键防重复）、run 置 `cancelled`、`dispatch_status='cancelled'`、`desired_run_id` 恢复；**响应丢失（mock 抛超时但消息实际已入 broker）→ `dispatch_status='unknown'`、冻结不释放、run 不置 cancelled、进入对账**（断言不出现"已退款任务继续执行"）；批量多章节任一冻结失败整体回滚；worker 原子认领：供应商调用前 CAS（status→running + dispatch_status→dispatched），已取消 run 认领失败 rowcount=0 立即终止、mock 供应商断言零调用。**R11 dispatcher 兜底（P0-1）**：模拟"事务提交后、首次派发前进程退出"→ stale-pending 扫描器租约认领重放、消息入 broker、run 最终 `dispatched`；`dispatch_attempts` 超上限转 `unknown` 人工对账（不无限重试）；**R11 账户锁（P0-2）**：双请求并发分别通过预检 → 冻结事务内 `pg_advisory_xact_lock(user_id)` 串行化、锁内重聚合余额 + 全部有效冻结统一裁决，断言冻结总额不超过余额；**R11 条件补偿（P1-4）**：run A 派发失败时 desired 已被 run B 接管 → 条件更新 rowcount=0 不覆盖指针，仅取消释放 run A（`predecessor_run_id` 为创建时持久化值）。
- **发布谓词按引擎（R9/P0-2）**：legacy_stems `full`/`audio_from_scripts`/`chapter_remix` 运行 `result_render_status='completed'` + 整章输出齐全 → 发布成功；`result_render_status='failed'` → 不发布；seed_scene 谓词不变。
- **运行作用域（R9/P0-3，R10 唯一约束 P0-4）**：跨 `chapter_audio` 的 output/artifact 复合外键 insert 被数据库拒绝；`desired_run_id`/`published_run_id` 指向其他 chapter_audio 的 run 被数据库拒绝；**删除被双指针引用的 run 被数据库拒绝（复合外键 ON DELETE RESTRICT，R10/P1-1）**；首次运行（script_only/full）在入队事务内创建唯一 active `ChapterAudio`（后台剧本生成不再负责创建，仅更新既有行）；**唯一 active 并发（R10/P0-4）**：真实 PostgreSQL 双事务并发首次创建同一章节——仅一个成功，loser 捕获 `IntegrityError` 后 `nested.rollback()` 重读复用（不抛 `InFailedSqlTransaction`）；软删除恢复与既有 active 行冲突返回 409；迁移确定性去重后无重复 active。
- **派生执行事实（R9/P0-4，R10 分阶段 P1-2）**：full 运行**分阶段冻结** `derived_execution_facts` 子项——剧本生成后冻结 `generated_script_facts`（+hash）、voice_binding 后冻结 `voice_resolution`（+hash）、scene_planning 后冻结 `scene_topology`（+hash），冻结过的子项不可覆盖（append-only）；恢复从最后一个完整阶段的下一阶段继续（不重跑已冻结阶段的非确定性过程、不读实时配置）；各子项 hash 失配报错并记录 `result_render_detail`；历史缺全部子项的 full 运行恢复被拒。
- **历史回填（R9/P1-1，R10 明确落点 P1-1）**：有 `audio_path` 的历史章节回填 `published_run_id` + published `ChapterAudioOutput` + `published_provenance='legacy_unverified'`；**无法确认 run 归属的产物回填到 synthetic migration run**（`run_type='migration_placeholder'`、`status='completed'`、`dispatch_status='cancelled'`、不可恢复/结算/重试/派发——复合外键合法成立）；seed 历史 `render_status` 保持 null（不回填精确 `rendered_all_seed`）；API 返回 `published_provenance` 字段且消费者渲染"历史产物（未验证）"；全部历史 run 的 `chapter_audio_id` 确定性回填（不留空）。
- **dialogue 审批锁后重算（R9/P1-2，R10 全局锁序 P1-4）**：审批与并发编辑交叉（读旧 head → 编辑提交 → 审批提交）时，审批在锁后重算失配返回 409，不把新剧本误标 approved；**编辑×审批交叉无死锁（R10/P1-4）**：真实 PostgreSQL 双事务并发测试——编辑（先锁 ChapterAudio 行 → dialogue head）与审批（同序 ChapterAudio → dialogue head）同时提交，断言无死锁且任一事务正常完成；voice_binding 双写遵守 Project → ChapterAudio → voice head 顺序。
- **voice_binding 并发（R9/P1-6）**：两个会话对不同章节并发提交 voice_binding 双写，断言 `audio_config` 写入被串行化（Project 行 FOR UPDATE），失败整体回滚、无分裂状态。
- **billing_usage_ledger（R9/P1-3，R10 状态机 P1-3）**：供应商调用前写 `status='pending'`（attempt_key），成功返回后转 `succeeded` 补 quantity/provider_request_id；同 run 同 attempt_key 重复写被唯一约束拒绝（重试幂等）；同 run 同 provider 同 request 同 usage_kind 重复 succeeded 被去重约束拒绝；失败请求不转 succeeded；**崩溃窗口**（供应商成功、本地未落账）恢复后 pending 记录仍在，按 attempt_key 补录 succeeded（无重复入账、无丢失用量）；`pricing_key` 参与结算单价匹配。
- **输出墓碑（R9/P2-3）**：清理后 `file_status='purged'` + `purged_at` 置位，登记与摘要保留；published 镜像列引用的文件禁止清理；`file_status='missing'` 被完整性校验暴露（不短路）。
- **任务-派发数据合同（R11/P0-3，R14/P1-a 统一）**：父任务 + N 条 `audiobook_task_dispatches`（每 run 一条，**子派发表无 `celery_task_id` 列**——查询/暂停/恢复/SSE 经 JOIN `ChapterAudioRun` 获得，删除一切 dispatch 与 run 的 celery_task_id 一致性断言）；N 个 worker 并发完成时父任务聚合为正确终态（全 succeeded→completed、部分失败→completed_with_partial_failure、任一 running→running、全 cancelled→cancelled）；暂停/恢复/取消按 run 级操作生效；`GET /tasks/{task_id}/status` 返回父聚合视图（含 children 摘要）；SSE 按 run 发出、前端按 job_id 聚合。
- **worker 租约（R11/P1-1）**：worker CAS 认领后崩溃（未续期未 ACK）→ `lease_expires_at` 到期后消息重投（`task_acks_late`/`task_reject_on_worker_lost`/`visibility_timeout` 配置生效）→ 新 worker 接管过期租约继续执行；claim_token 不匹配的续期被拒；先落库后 ACK（任务完成/失败落库后才 ACK）。
- **ledger 四态（R11/P1-2，R14/P0 统一命名）**：确定失败转 `confirmed_failed`（不结算）；无法判定转 `manual_reconciliation`（不自动结算，人工对账后转态再结算）；"供应商不返回 request ID"的成功调用合法转 succeeded（`provider_request_id` 可空，非空时 `(run_id, provider, provider_request_id, usage_kind)` 部分唯一索引去重）。
- **provider 能力声明（R11/P1-3）**：声明"不支持外部幂等 + 不可查询"的 provider 在"外部成功、本地未落账"窗口后转 `manual_reconciliation`，mock 供应商断言零二次调用；支持幂等/查询的 provider 自动补录 succeeded。
- **canonical 去重（R11/P1-5）**：迁移对同 `(audiobook_project_id, chapter_id)` 组内按 canonical 优先级（有效已发布产物 → approved script + 审核证据 → 完整字段数 → 更新时间 → id）选保留行；产物/审核证据合并迁移到 canonical 行（runs/outputs 改指、字段复制、物理文件保留并登记）；断言不调用 `soft_delete_older_duplicates` 的 unlink 物理删除逻辑；迁移后无重复 active 且部分唯一索引建成。**迁移执行时序（R19/P1-3，R20，R21）**：迁移全局单实例（`pg_try_advisory_lock(MIGRATION_VERSION_LOCK_KEY)` 获取失败即退出，R21/P1-2；**会话锁用专用非池化连接持有并在 finally 解锁：实例 A 获锁后异常退出 → finally 解锁/关闭连接 → 实例 B 随后成功获锁；实例 A 获锁后进程死亡 → 数据库断连自动释放 → 实例 B 可重新启动迁移（R22/P1-3）**）；每组事务：组级 advisory lock → progress FOR UPDATE → 锁后重查 status（completed 跳过、仅 pending/failed 认领）→ 事务 A 完成业务 + `completed` 同事务提交（提交后该组才可跳过）；事务 A 失败回滚后事务 B 独立短事务写 failed + 脱敏 failure_detail + attempts/last_failed_at/last_error_code（不随业务回滚消失；**事务 B 为 fail-closed 条件更新（`ON CONFLICT DO UPDATE ... WHERE status <> 'completed'`）——真实 PostgreSQL：事务 A 成功 commit → 模拟客户端在 commit 响应前断线 → 重试逻辑不得把 completed 改为 failed、不重复创建 synthetic run/output/文件登记且 attempts 不递增；attempts 仅确认失败并写入事务 B 时递增，R22/P1-2**，R21/P1-1）；中断后从首个未完成组续跑、失败组带原因不伪装完成；重试读进度表 completed + 重跑组级一致性校验通过才跳过（覆盖事务 A 提交后断线的不确定结果）；重复 active 全部清理完成后才创建部分唯一索引——创建前验证 SQL（全表无重复 active）返回空、在 Alembic 事务外（或独立 revision `autocommit_block()`）执行 CONCURRENTLY、创建后断言 `pg_index.indisvalid = true`；创建中断留下 INVALID 索引 → 下次执行按身份校验（schema/表名/`indisvalid=false`/`indisready`/`pg_get_indexdef` 与预期定义一致）识别并 `DROP INDEX CONCURRENTLY` 清理 → 重建成功 → `indisvalid=true` 且 indexdef 与预期一致；同名但定义不同的有效索引存在时停止 Contract 不自动删除（R21/P2-2）；Migrate 期间已处理组由应用层写闸门/advisory 锁保护（非索引，R20/P1-2）。
- **published 值域收窄（R11/P2-1）**：`ChapterAudio.render_status` 值域 CHECK 只允许 {rendered_all_seed, rendered_with_fallback, stale, null}；`result_render_status` 为 Seed 四态；首次失败/人工评审不发布 → published=null、已有产物重渲染失败 → published 保持旧成功值。
- **run 不可删（R11/P2-2）**：repository/service 层无 `DELETE FROM chapter_audio_runs` 物理删除入口（全部改 `deleted_at` 墓碑或禁止）；被指针引用的 run 删除被数据库拒绝；未被任何指针引用的终态 run 的不可删由服务层策略保证（审计/账单/回填引用仍成立）。
- **worker 首认领/过期接管拆分（R12/P0-1）**：真实 PostgreSQL 双事务模拟"认领成功 → worker 崩溃 → 租约过期 → 消息重投"——新 worker 的"过期接管"CAS（`status='running' AND lease_expires_at < now()`）命中并接管，断言 run 继续执行而非永久卡死 `running`；首认领 CAS 对已 running 的 run 不命中（rowcount=0）；接管分支对 cancelled run 拒绝；两分支 CAS 均同步更新 claim 三字段（子派发表不自存投影字段，R13/P1-d）。
- **心跳与阻塞调用解耦（R13/P1-e 收紧）**：非幂等 provider 强制 request_timeout < lease（否定仅独立 heartbeat 而不约束请求超时）；可查询/幂等 provider 的 heartbeat 独立续期（独立线程/调度）；接管者先按证据恢复查询（`provider_request_id`/`encrypted_result_url`/`idempotency_key_sent`），确认可幂等重放才允许再次调用供应商；旧请求持续超 lease 窗口下 token fencing 拒绝旧 worker 后续落库；mock 供应商零重复调用。
- **celery_task_id cutover（R12/P0-2）**：真实 PostgreSQL 迁移测试——构造三类数据（多 run 共用旧 Celery ID / null ID / 旧活动任务），按五步顺序（分类 → parent/child 回填 → null 回填 → drain/cancel → 施加约束）执行，断言：回填 id 唯一且 `legacy-` 前缀、旧活动任务取消后不再回写 run 状态、`NOT NULL` + `UNIQUE` 约束生效、`legacy-` 前缀 run 的查询/暂停/恢复/SSE 走展示投影（不按 broker task id 关联）。
- **账户锁收敛（R12/P0-3）**：共享 points mutation service 单测——拆书/小说协同/短剧冻结/管理员调账与有声书冻结经同一 service 同一 advisory 锁键并发交错，断言冻结总额 ≤ 余额（不变量成立）；绕过 service 直接调旧冻结入口的路径在验收测试中被标记为穿透（不允许生产调用）。
- **派发单一事实源与终态矩阵（R13/P0-a+R13/P1-a 修正，R14/P1-c fail-closed，R15/P0-1/P1-1 补值域与优先级）**：子派发表无 celery_task_id 列（查 JOIN run，R13/P1-d）；复合外键拒绝 `chapter_audio_id` 不属于该 run 的子派发插入；父聚合前先执行 `normalize_run_status` SQL CASE 投影（pending/queued→queued、completed→succeeded、**expired→cancelled（R15/P0-1）**、canceled/cancelled→cancelled、**paused/pause_requested→pause_requested，R14/P1-c**），再基于规范化值做互斥矩阵（**计数穷尽规则（R17/P1-2）：①任一 unknown fail-closed → ②任一进行中 → ③全 succeeded → ④全 cancelled → ⑤至少一 succeeded 且存在失败/取消 → ⑥无 succeeded 且至少一 failed——替代 R15/P1-1 的"unknown > 进行中 > cancelled/failed 终态组合 > 全 succeeded"优先级表述：旧表述对 {cancelled, failed} 无定义结果，计数规则穷尽全部组合**），断言分支（全 cancelled/全 failed/部分成功/全 succeeded/有进行中）不并列命中且 `completed_with_partial_failure` 写入父表成功（VARCHAR(32) + CHECK 放行）；**增补用例（R14/P1-c + R15/P1-1）**：合法 `pause_requested` run → 父任务投影 `running`（非 unknown）；真实未知值（如历史遗留 'weird'）→ 父任务投影 `failed` + `detail_json` 审计错误 `aggregation_unknown_status`（断言非无分支返回）；**三个 unknown 组合**——`{unknown, failed}`/`{unknown, running}`/`{unknown, succeeded}` 均先命中 fail-closed 分支、不产出 `completed_with_partial_failure`（断言 unknown 置顶优先级）；**R17/P1-2 计数穷尽补充**——`{cancelled, failed}` → `failed`、`{cancelled, failed, succeeded}` → `completed_with_partial_failure`（另含 `{failed, failed}` → failed、全 cancelled → cancelled、全 succeeded → completed），断言每一规范化组合恰命中一条分支（穷尽且互斥）；`job_id` = `task:{AudiobookTask.id}` 命名空间字符串；`GET /tasks/{task_id}` 按 `task:{id}` 与 `celery_task_id`（兼容期）分别解析；SSE 事件携带 `run_id` + 父 `job_id`。
- **ledger 结算封口（R13/P1-b strict barrier，R14/P1-e 幂等数据合同，R17/P0 统一 finalizer）**：run 存在 `pending`/未收敛 `manual_reconciliation` 时结算被拒、冻结保留（断言不写入 settle 事件）；收敛后由统一 finalizer 执行唯一一次最终 settle（R17/P0：任何路径不得绕过 finalizer 直接 settle——run 未终态时人工收敛只提交 ledger 与审计，幂等域 = run 级 billing_key：账户锁内 `_latest_event_kind==settle` 短路生效、`admin_operation_logs` 部分唯一索引（`resource_id` 作用域）拒绝同账户同 billing_key 第二条 settle、复合串作 billing_key 传入被拒）；**两个并发 settle 事务（真实 PostgreSQL）断言只产生一条 settle 事件、一次积分扣减**。
- **恢复证据持久化（R13/P0-b 证据字段落地）**：断言 `encrypted_result_url`/`result_url_expires_at`/`capability_snapshot_json` 随状态机写入（pre_call 写 `idempotency_key_sent`/`capability_snapshot_json`，post_call 写 `provider_request_id`，result_persisted 写 `result_url_persisted_at`+`encrypted_result_url`+`result_url_expires_at`）；恢复决策四种证据组合（有 `provider_request_id`→query；有 `encrypted_result_url`→拉取；确认幂等键→replay；无证据→manual_reconciliation 零二次调用）；修改 `provider_dispatch_capabilities` 后重放历史调用仍按 `capability_snapshot_json` 快照决策。
- **run 墓碑与级联删除（R12/P1-4）**：`ChapterAudioRun.deleted_at` 生效；`ON DELETE RESTRICT` 生效（硬删项目/章节被数据库拒绝）；项目软删除（置 `deleted_at`）后 run 行与 ledger/output 关联保留；repository 删除入口全部置墓碑。
- **dispatched 未认领重投（R12/P1-5）**：mock `apply_async` 成功（`dispatch_status='dispatched'` + `dispatched_at`）后 worker 从未认领 → 超 `first_claim_deadline` 后 dispatcher 未认领重投 CAS 命中（`dispatched && claim_token IS NULL && 超时`）、复用固定 celery_task_id 重投、重置 `dispatched_at`；broker 实际仍存旧消息时 worker lease 防重复外部调用（mock 供应商单次调用）。
- **ledger DDL 可执行（R14/P0）**：真实 PostgreSQL 建表——`uq_billing_usage_ledger_dedup` 引用 `provider_request_id` 建表成功（无 `request_id` 残留引用）；`status='manual_reconciliation'`（21 字符）写入 String(32) 成功不被拒绝。
- **父 CHECK 两阶段收窄（R14/P1-b）**：宽 CHECK 期旧 API/旧 worker 写父表暂停态成功；收窄后父表写暂停态被数据库拒绝而 run 级暂停正常；清洗 + 重新聚合断言父表无 `pause_requested`/`paused` 残留。
- **dispatcher 结果回写 fencing（R14/P1-d）**：真实 PostgreSQL 双 dispatcher——A 认领 token A、阻塞、claim 过期；B 认领 token B 并投递成功；A 迟到返回明确失败/成功均被 token CAS 拒绝（rowcount=0、无补偿副作用：run 不取消、冻结不释放、desired_run_id 不变）；B 的 claim 保持、已投递 run 不被取消。
- **settle 幂等数据合同（R14/P1-e，R15/P0-2 索引作用域与清洗）**：并发 settle 事务（真实 PostgreSQL 双会话）断言只产生一条 settle 事件、一次积分扣减；部分唯一索引（`resource_id` 作用域）拒绝同账户同 billing_key 第二条 settle——不同 actor 对同一 target 账户同样被拒；预置重复历史行（最新一条不置位、其余 `dedupe_superseded=true`）后索引创建成功且事件流聚合过滤标记行；复合串作 billing_key 传入被拒绝（无 active freeze）。
- **run 状态值域含 expired（R15/P0-1）**：真实 PostgreSQL——迁移后写 `run.status='expired'`（候选 supersede/临时片段过期清理路径）不被 CHECK 拒绝；`normalize_run_status` 投影 `expired→cancelled`（终态非结果）；历史 `completed` 行保持数据库值、查询投影 succeeded（断言清洗不改写数据库态）。
- **manual_reconciliation 人工收敛（R15/P1-4，R16/P0 + P1-1 + P2-1 强化）**：非管理员 403；reason/evidence 缺失被拒；succeeded 缺 quantity/quantity≤0 被拒（422，CHECK 前校验）；**初始 quantity=NULL 的 ledger 人工确认成功合法转 succeeded（真实 PostgreSQL，`ck_billing_usage_ledger_succeeded_fields` 放行）**；usage_kind/unit/pricing_key 与 run billing_snapshot 不匹配拒绝收敛（422）；**CAS 与审计、strict barrier、最终 settle 同一事务——故障注入①：CAS 成功后 settle 前抛异常 → 整体回滚（ledger 回 manual_reconciliation、无审计残留、冻结保留）、再次请求成功；故障注入②：settle 写入失败 → 整体回滚，重试后仅一条 settle 事件并释放冻结**；run 有其他未收敛 ledger 时提交当前 ledger 与审计、冻结保留（settle 由统一 finalizer 在 run 终态且 barrier 通过后完成，R18/P0）；`ledger_reconciliation_audits` 记录全量断言（含 confirmed_quantity 与 ledger.quantity 一致）；**append-only：repository 无 update/delete 入口 + 数据库级强制（R16/P2-1，R19/P2-2：BEFORE UPDATE OR DELETE trigger 拒绝或应用角色仅 SELECT/INSERT；测试直接执行 SQL 断言数据库拒绝修改/删除）**。
- **计费封口与可结算性（R17/P0 + R17/P1-3 + R17/P1-4）**：真实 PostgreSQL 双会话——finalizer（run 已执行终态 + 无有效 lease）与 worker 新建下一条 `pending` ledger 并发，断言不可能出现"settle 在先、ledger 在后"（settle 已提交则建账 CAS `AND billing_finalized_at IS NULL` rowcount=0、建账在先则 barrier 不通过不 settle）；已封口 run 的认领/接管/建账全部被拒（mock 供应商零调用）；`billing_finalized_at` 一次性置位不可回退；run 未终态人工收敛只提交 ledger+audit、run 结束后统一 finalizer 一次结算；`billing_account_user_id` 创建 run 时与冻结同一事务写入、项目所有者变化仍按原账户结算、freeze 三字段任一不匹配拒绝收敛；统一 ledger transition service 可定价性校验（pricing_key 存在、unit 一致、snapshot 有效、quantity>0）——校验失败自动路径转 `manual_reconciliation`、人工收敛 422；历史不可恢复 succeeded 迁移转 `manual_reconciliation` 拒绝结算。**finalizer 主路径（R18/P0；R19/P0 统一锁序）**：worker 正常成功——终态事务先取账户锁 → run 行 FOR UPDATE → 取锁后重校验 status/claim_token/封口（不用锁前读取结果）→ 终态 CAS 清租约 + 关账 → 同事务 finalizer 当场 settle 并释放冻结（主路径断言，不依赖人工收敛入口；取锁后重校验失败回滚终止）；**锁序双会话验证（R19/P0）**：会话 A worker 终态主路径 × 会话 B 人工收敛（同账户）并发交错，断言两条路径加锁顺序完全相同（账户锁 → run 行锁）且无死锁（不是单纯“finalizer 与建账并发”，而是两条 mutation 路径的同锁序验证）；取消/失败——关账后无 pending 残留（无供应商证据 → confirmed_failed、已发出/结果不明 → manual_reconciliation），全部 confirmed_failed 时 barrier 通过当场 settle；租约未清且未过期时 finalizer 拒绝，自然过期后 beat 扫描器（`billing_finalizer_scan`：`终态 ∧ billing_finalized_at IS NULL ∧ 无有效租约`）重试成功；建账为独立短事务锁当前租约（`status='running' AND claim_token=:token AND billing_finalized_at IS NULL` FOR UPDATE），谓词不满足拒绝建账（不得只查封口字段）。**审计 CHECK rank 单调（R18/P1-1）**：succeeded 收敛原记录已 result_persisted 通过单调 CHECK（new ≥ prev，pre_call=1 < post_call=2 < result_persisted=3）。**不可变 trigger（R18/P2）**：`billing_finalized_at`/`billing_account_user_id` 非空后清空/修改被数据库 trigger 拒绝（NULL → 值回填放行）。**pricing_key 映射（R18/P1-3）**：remix 用量经 transition service 自动转 succeeded（prices 含 remix 条目），usage_kind → pricing_key → prices 键 → unit 映射为唯一依据；**unit 常量表同源断言（R19/P1-1）**：`prices[*].unit` 与 ledger.unit 同为计量单位 second|char（币种由价格字段名表达），映射与值域出自唯一常量表——快照生成/transition service/人工收敛/测试共用，断言无重复硬编码、正常记录 pending→succeeded 不被单位校验误拒。

### 前端（区分配置 Vol 不变）

- `resolveGeneratedChapterIdsFromProjects`：按 engine_mode 过滤；seed_scene 完成条件判定。
- `resolveChapterStateById`：章节状态表渲染（published 四值 + desired 专属态组合，R11/P2-1）；exportable/locked 语义正确（**locked = 禁止覆盖式初始生成与直改已发布产物，场景编辑器仍可提交 revision**）。
- `buildProjectAudioConfigPayload`：输出引擎分支结构，旧字段 persist 兼容。
- 引擎切换：章节状态刷新 + 角色绑定重载 + audio_fx 隐藏显示。
- 场景编辑保存：`base_revision_hash` 传递 + 409 处理 + `revision_heads` 更新。
- 场景列表渲染与试听 URL 处理。


## 8. 风险与边界

### 8.1 旧数据兼容性风险

- **engine_mode 迁移置信度**：Seed 引擎推断（§2.1 四项证据）仅能覆盖有明确 Seed 标记的历史批次。早期 Seed 探索阶段（`SEED_SCENE_CHECKPOINT_TYPE` 未引入前）的运行可能无法被正确归类为 `seed_scene`。已决策：**引擎证据不足的批次标记 `legacy_unverified` 并禁止恢复**（不允许回填为可恢复的 `legacy_stems`——误标 frozen 会导致恢复按错误引擎执行）；后续发现错误归类可手动修正快照状态。
- **快照不可重建**：`legacy_unfrozen` 批次（JSON 损坏等）禁止恢复。已决策：不存在"尽力而为恢复"选项，用户必须重新生成批次。
- **voice_mapping 存量数据**：`voice_mapping` 列废弃写入后，存量数据仅保留供展示与审计（§2.1），**不参与任何运行输入**。迁移脚本不清理存量 `voice_mapping` 数据，仅阻止新写入。

### 8.2 并发与数据完整性边界

- **场景编辑并发**：§2.9 的 `FOR UPDATE` 行锁策略依赖 PostgreSQL `READ COMMITTED` 隔离级别。在 `REPEATABLE READ` 或 `SERIALIZABLE` 级别下，`SELECT FOR UPDATE` 锁不到不存在行的问题仍然存在（首次编辑时 head 行不存在），但唯一约束（`(project, chapter, edit_type)`）在任意隔离级别下均保证只有一个事务能成功插入。
- **两阶段流程复制剧本**：切换引擎后复制已审批剧本到新批次时，源 `ChapterAudio.script_json` 可能在复制窗口内被修改（dialogue 编辑）。已决策：复制批次创建时读取 `script_json` 当前快照，不跨事务锁定源行。若窗口内有 dialogue 编辑，新批次拿到的是编辑前的剧本版本——不影响正确性，但用户可能需要手动触发重渲染。
- **voice_binding 双写并发（R9，P1-6）**：voice_binding 双写（`SceneEditRevision` + `Project.audio_config` 分支）在同一事务内以 `Project` 行 FOR UPDATE 串行化；不同章节并发提交时后提交者不会静默覆盖前者（后者在前者提交后才读改写），任一步失败整体回滚——不允许出现"revision 已写、配置未写"的分裂状态。
- **重渲染并发（R7）**：同一章节的多个重渲染请求可能创建多个 `ChapterAudioRun`。完整发布事务（§2.4 规则 4）以 `desired_run_id` 为 CAS 条件：完成回调 `WHERE desired_run_id = :run_id` 原子决定哪个 run 发布，不阻断并发创建多个运行记录；**只有发布成功的 run 才切换镜像列、输出登记与 artifact 状态**（旧已发布 run 的产物在发布事务内 superseded），未发布的 run 保持 staged（不激活、不可试听）——物理文件因 run 级路径天然隔离，晚完成 run 的文件不会覆盖已发布文件。
- **派发结果未知（R10，P0-1）**：`apply_async` 抛超时/网络类异常不代表 broker 未接收——把"结果未知"当作"确定未投递"执行补偿（释放冻结 + 置 cancelled）会使已退款任务被 worker 继续执行并产生供应商费用（现状活动检查仅拒绝 cancelled run，且 full/`audio_from_scripts` 在供应商调用前无原子认领检查）。已决策：结果未知时 run 保持 `pending`、`dispatch_status='unknown'`、**不释放冻结、不置 cancelled**，进入对账流程（查询 broker/任务状态：确认已执行 → 补记 `dispatched` 并保留 run；确认未执行 → 才走补偿；长期未知由人工处理）；**worker 原子认领（供应商调用前 CAS，rowcount=0 立即终止不调用供应商）与 `dispatch_status` 状态机是最低保证**——认领成功即确认 broker 确已投递（unknown 对账的关闭条件）；**run 即 outbox + 独立 dispatcher 重放为最低要求（R11/P0-1，升级 R10 的"可选增强"表述）**——run 行派发意图字段（`dispatch_status`/固定 `celery_task_id`/`dispatch_attempts`/`next_dispatch_at`/claim 字段）与业务同事务落库，stale-pending 扫描器租约认领重放，消除"事务提交后、首次派发前进程退出"的悬挂窗口；独立 message 表实体（多消费者/按序投递）仍可不做；unknown 窗口收窄为"dispatcher 认领后 `apply_async` 响应丢失"的窄窗，由对账流程与租约过期接管处理；**已投递未认领窗口（R12/P1-5）**：消息成功投递后、worker 尚未 CAS 认领前（`dispatch_status='dispatched'` 且 `claim_token IS NULL`），若消息在 broker 侧丢失/过期/被清理，`pending` 扫描器不会再处理它——dispatcher 以 `dispatched_at` + `first_claim_deadline`（须小于 `visibility_timeout`）判定未认领超时，按独立 CAS（`dispatched && claim_token IS NULL && dispatched_at + :first_claim_deadline < now()`）**复用固定 task id 重投**并重置 `dispatched_at`，worker lease 保证即使 broker 实际仍存旧消息也不产生重复外部调用。
- **全局锁序（R10，P1-4）**：普通编辑（先锁 head 再更新 `ChapterAudio`）与审批（先锁 `ChapterAudio` 再锁三条 head）锁序相反，交叉形成 head→ChapterAudio 与 ChapterAudio→head 经典死锁。已决策：全部编辑/审批/voice_binding/快照捕获路径统一锁序 **`Project（需要时）→ ChapterAudio 行 → dialogue head → director_override head → voice_binding head`**——普通编辑在锁 head 前先锁 `ChapterAudio` 行（与审批一致），任何路径不得以 head 为第一把锁；真实 PostgreSQL 双事务并发测试覆盖编辑×审批交叉场景（§6 验收 53）。

### 8.3 场景音频 artifact 与 run 级输出保留策略

- **artifact 物理文件保留期**：`status='superseded'`/`deleted_at` 置位后物理 artifact 文件保留 30 天，由定时任务（`scripts/cleanup_expired_artifacts.py`）清理；staged 停留超过 30 天且其 run 已终态的 artifact 同样回收。审计端点可访问已 superseded 但物理文件仍存在的 artifact。
- **run 级输出与整章文件保留期（R8，解决"ChapterAudioOutput 与 run 级整章文件无保留/删除/配额策略"；R9 墓碑化，P2-3）**：
  - `ChapterAudioOutput.status='published'` 的登记与其整章文件（`audio_path`/`subtitle_path`）**不清理**（当前可导出产物）；被 supersede 的旧 run 输出（published → superseded）登记与文件保留 30 天（审计与回滚窗口），超期由清理任务回收；
  - **清理只删物理文件并置墓碑（R9/P2-3）**：删除文件后登记行保留，置 `file_status='purged'` + `purged_at`——登记与账单/导出摘要继续保留可审计，不出现"登记消失导致历史摘要断裂"；发现物理文件缺失但登记仍为 present 时置 `file_status='missing'`（幂等短路一致性检查与完整性校验暴露，§2.4 规则 4 b）；
  - `status='staged'` 且所属 run 已终态（completed/failed/cancelled）的输出：保留 30 天后回收（未发布候选）；run 未终态（进行中/暂停）的 staged 输出不清理；
  - 文件删除前校验无其他登记引用同一物理路径（同一文件不得因多个登记而误删）；**被 `ChapterAudio.published_run_id` 镜像列引用的输出文件禁止清理**；
  - 运行目录按既有任务清理规则删除后，已发布试听/导出不受影响（登记指向的物理文件由上述策略单独管理）。
- **存储位置**：`backend/data/scene_audio_artifacts/`，按 `{artifact_id[:2]}/{artifact_id[2:4]}/{artifact_id}` 分片存储以避免单目录文件过多；整章输出文件位于 run 级目录（含 run_id 段）。
- **配额上限**：每个项目 `scene_audio_artifacts` 表记录数上限 10,000 行（不含 `deleted_at IS NOT NULL` 的已清理记录），超出后新登记被拒绝，需先完成旧 artifact 物理清理；`chapter_audio_outputs` 每 run 至多一条（run_id 唯一约束），整章输出文件总量受 run 保留期约束。

### 8.4 前端兼容性边界

- **旧前端版本访问**：API 改造后（§1.3）旧的 `ProjectAudioConfig` Pydantic 模型不再接收 `engines` 字段，旧前端提交的 `characters`/`audio_fx`/`tts_models` 顶层字段仍被接受并归一化为 `engines.legacy_stems` 分支。但是，旧前端看不到引擎分支状态（`chapter_audios[].render_status`、`engine_mode` 过滤的批次列表），可能导致章节状态显示异常。已决策：不要求旧前端全量升级，异常仅影响状态展示，不破坏生成功能。
- **灰度发布顺序**：必须先部署后端（API 兼容层），再部署前端。后端向后兼容期至少保留 1 个发布周期。

### 8.5 计费与审计边界

- **冻结算费（R8，R9 六步闭环，R10 事务所有权 + 可靠派发 + ledger 状态机）**：按 §2.1 六步顺序执行——①入队前捕获不可变 pricing snapshot（每 run 独立）→ ②准入预检（snapshot 计价事实 + 实时账户余额）→ ③同一事务创建 run + 持久化 `run_input_snapshot`（含该 billing_snapshot）+ 更新 `desired_run_id` **+ 同事务冻结**（冻结失败整体回滚；**R10/P0-3：整个入队调用图（`create_task`/`attach_celery_id`/`create_run`/`create_runs`/`enqueue_chapter_runs`/`_create_points_billing_event_log`/`_safe_record_audiobook_billing_freeze`）全部只 add/flush 无内部 commit，事务所有权归最外层应用服务；R12/P0-3：冻结/结算/释放必须经共享 points mutation service 在同一 advisory 锁键下执行（与拆书/小说协同/短剧冻结/管理员调账统一），否则账户级不变量不成立**）→ ④**事务提交后派发由 dispatcher 兜底**（R11/P0-1：run 即 outbox——派发意图 + 固定 `celery_task_id` 同事务落库，stale-pending 扫描器租约认领重放；R10/P0-2：每 run 独立消息 + 独立 task id；三态：明确失败→**条件补偿（锁定 `ChapterAudio` + `UPDATE ... SET desired_run_id = :predecessor_run_id WHERE id = :chapter_audio_id AND desired_run_id = :failed_run_id`，rowcount=0 不覆盖新指针，R11/P1-4）**、**结果未知→`dispatch_status='unknown'` 不释放冻结走对账（P0-1）**、成功→dispatched；worker 供应商调用前原子认领）→ ⑤批量章节策略（冻结阶段任一失败整体回滚；派发阶段逐 run 独立处理，已成功派发者不受影响）→ ⑥结算（run 快照内嵌 snapshot + **`billing_usage_ledger` 实际用量，R10/P1-3：供应商调用前写 pending（attempt_key）→ 成功转 succeeded 补 quantity/provider_request_id，崩溃窗口不丢用量不产生第二笔费用；R13/P1-b 结算封口 strict barrier + R14/P1-e 幂等数据合同：run 全部 ledger 必须已终态（无 pending/未收敛 manual_reconciliation）才允许最终结算，未收敛保留冻结直至人工收敛；**run 执行终态后由统一 finalizer 执行唯一一次最终 settle（R17/P0：任何路径不得绕过 finalizer 直接 settle，人工收敛 run 未终态时只提交 ledger 与审计，见下方“统一 finalizer 结算”边界（含 R18/P0 触发路径：终态事务按全局统一锁序先取账户 advisory 锁、取锁后重校验、CAS 清租约 + 同事务调 finalizer（R19/P0 统一锁序） + beat 扫描器兜底 + 取消/失败按证据关账）；一次性普通 settle，幂等域 = run 级 billing_key 本身——账户 advisory 锁内"已 settle"短路 + `admin_operation_logs` 部分唯一索引（`UNIQUE (resource_id, (request_params->>'billing_key')) WHERE operation_type='POINTS_BILLING_SETTLE' AND COALESCE(request_params->>'dedupe_superseded','false') <> 'true'`——**账户作用域 `resource_id`**（`user_id` 是操作用户语义、`resource_id=target_user_id` 才是实际账户，R15/P0-2）；历史重复 settle 置 `dedupe_superseded=true` 退出索引谓词且事件流聚合过滤）数据库兜底，复合串仅作 `request_params.settle_scope` 审计描述、不得作为 billing_key 传入，不再引入 supplement）**）。预检/冻结/结算只消费 `billing_context.billing_snapshot` 内嵌计价事实（各 provider/model 单价、计价单位、`user_price_basis`/`user_price_rate`/`provider_discount_capture_rate`/`provider_discount_rate`/`provider_discount_source`/`points_per_yuan`/`freeze_buffer_rate`/`margin_warning_rate`/`negative_margin_block_enabled`/`settlement_formula_version`，§2.1）。**计费作用域为 run 级（R8 决策，R9 统一命名）**：`build_audiobook_billing_key = audiobook:{audiobook_project_id}:run:{run_id}`（源小说 `project_id` 仅展示聚合），同批次多次运行各自冻结/结算/幂等；批次级账单为展示层聚合；历史批次级冻结记录保持兼容（仅展示聚合）。结算时仍以同一内嵌快照为准，即使用户在该批次多个运行期间升级了账户层级或定价规则已变更；定价事实缺失的历史运行（`run_input_snapshot` 回填不可行）拒绝重新结算，仅展示；**用量事实源（R9/P1-3，R10 状态机 P1-3）**：结算以 `billing_usage_ledger` 中 `status='succeeded'` 记录汇总 × `billing_snapshot` 计价事实为准（`pricing_key` 匹配多模型单价；调用前 pending → 成功转 succeeded，`(run_id, attempt_key)` 内部去重 + `(run_id, provider, provider_request_id, usage_kind)` 供应商侧去重（R14/P0 统一命名）；`quantity > 0` 由 CHECK 保证），不依赖无持久化的内存计数；pending 记录不参与结算。
- **统一 finalizer 结算（R17/P0 计费封口；R18/P0 触发协议与主路径；R19/P0 全局锁序统一）**：最终结算只由统一 finalizer 在单事务内执行——固定锁序 `pg_advisory_xact_lock(billing_account_user_id)` → `ChapterAudioRun` 行 FOR UPDATE →（后续如需锁 ledger 行，统一按 `ledger.id` 升序，三层锁序第③层，R20/P1-1，R21/P2-1）→ 校验（run 已执行终态 + 无有效 worker lease（`lease_expires_at IS NULL` 或已过期——**执行终态 CAS 同步清租约（R18/P0），或租约自然过期**）+ `billing_finalized_at IS NULL` + strict barrier：全部 ledger 已终态）→ 置 `billing_finalized_at` → 唯一一次 settle → 单次提交；**该固定锁序是全局强制合同（R19/P0；R20/P1-1 纳入 ledger 行；R21/P2-1 精确化：三层锁序——账户 advisory 锁 → run FOR UPDATE → ledger FOR UPDATE（按 id 升序）——加锁仅这三层，持锁后按锁内写入顺序执行：ledger 状态更新 → 必要时插入 `LedgerReconciliationAudit`（仅人工收敛路径，worker 成功转态/confirmed_failed 自动关账/纯 finalizer 重试不插入）→ strict barrier → 置 `billing_finalized_at` 封口 → settle 事件写入（单次 commit），完整合同见 §2.9）：所有路径必须按“账户锁 → run 行锁”（及后续 ledger 行锁）顺序执行；禁止任何路径先获取 run 行锁再获取账户锁，也禁止在账户锁与 run 行锁之前先锁 ledger（按 ledger_id 先 FOR UPDATE 再取账户锁）——两种反序均构成死锁环（见 §2.1 执行终态写协议）**；**任何路径（含人工收敛接口）不得绕过 finalizer 直接 settle**——人工收敛后 run 未终态时只提交 ledger + 审计、不 settle、不置封口，等 run 真正结束后由 finalizer 结算。**三条触发路径（R18/P0，修复 R17 主路径缺口——R17 只定义前置未定义触发，worker 完成握租约致前置永不满足、过期无重试、收敛入口进不去，成功 run 冻结永久挂死）**：①worker 终态主路径——终态事务严格按上述固定锁序执行（R19/P0：先取账户锁 → run 行 FOR UPDATE → **取锁后重新校验 status/claim_token/封口，禁止使用锁前读取结果** → 终态 CAS 清租约（`claim_token/claimed_at/lease_expires_at=NULL`）→ 按证据关账 → finalizer 逻辑 → 单次 commit，§2.1 执行终态写协议），成功 run 当场结算并释放冻结；②人工收敛联动——run 终态 + 无租约 + barrier 通过则同事务封口结算；③beat 扫描器兜底——`billing_finalizer_scan` 定期扫描“执行终态 ∧ `billing_finalized_at IS NULL` ∧ 无有效租约”重试（run 行即结算意图记录，不引入新表）。**取消/失败按证据关账（R18/P0）**：写 run cancelled/failed 必须同事务关账本 run 全部 pending（无供应商证据 → `confirmed_failed`、已发出/结果不明 → `manual_reconciliation`，零二次调用），不得残留 pending（否则 barrier 永远过不了、冻结挂死）。**建账合同（R18/P1-2）**：worker 每次新建 ledger attempt 为独立短事务，锁**当前租约**（`SELECT ... WHERE status='running' AND claim_token=:token AND billing_finalized_at IS NULL FOR UPDATE`——谓词同时校验执行状态、当前租约 token 与封口字段，不得只查封口字段），非首次认领事务（同 run 多次 TTS/ASR/remix 调用若绑首次认领要么握长事务、要么提交 pending 时丢 run 锁）；finalizer 与 worker 以 run 行锁串行化（建账短事务仅持 run 行锁、不取账户锁，无锁序反转，R19/P0），不可能出现“settle 在先、ledger 在后”，杜绝结算后新增用量导致的永久少扣费。
- **结算账户（R17/P1-3）**：settle 与账户锁一律以 `ChapterAudioRun.billing_account_user_id`（创建 run 时从冻结事务 `target_user_id` 持久化的不可变值，同时落 `run_input_snapshot.billing_context`）为权威来源，禁止从当前 `Project.user_id` 推导；结算前强制校验 active freeze 的 `resource_id`/`billing_key`/`run_id` 与 run 完全一致——项目归属变化后仍结算原账户，锁错账户、找不到原 active freeze 均不可能。
- **可结算性（R17/P1-4）**：只结算同时具备有效 `pricing_key`/`billing_snapshot_id`/`unit`/`quantity` 的 `succeeded` 记录（数据库 CHECK + 统一 ledger transition service 双保险，worker 自动路径与人工收敛共用同一可定价性校验）；历史不可验证记录显式转 `manual_reconciliation`（`legacy_unverified` 语义）并拒绝结算，不以 NULL 静默放行。
- **历史计费差异**：`legacy_unverified` 批次的快照不保证代表真实历史输入，其计费信息仅用于展示，不作为账单凭证。
- **审计端点访问控制**：`audit-stream` 端点的权限粒度为管理员/项目所有者，不支持更细粒度的审计角色分发。需要审计角色分离的场景需前端叠加功能限制。

### 8.6 非目标（明确的排除项）

- 不支持三引擎或更多引擎架构；`engine_mode` 值域固化为 `legacy_stems`/`seed_scene`，不含扩展接口。
- 不支持跨引擎批次合并（例如：将 legacy_stems 第 1 章的音频与 seed_scene 第 2 章的音频导出为同一文件）。
- 两阶段流程不自动触发新批次的 `script_only` 阶段（用户已审批剧本不应无端重跑审核流程）。
- 不支持在场景编辑器中直接编辑 checkpoint（始终通过 revisions 链间接编辑）。
- 不支持在批次创建后修改 `engine_mode`（冻结语义）。
