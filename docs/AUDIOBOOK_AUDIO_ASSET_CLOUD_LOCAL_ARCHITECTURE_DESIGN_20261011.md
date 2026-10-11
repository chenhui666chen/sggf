# 有声书音频资产：云端真源 + 本地缓存 + 项目级回收 设计

日期：`2026-10-11`
状态：**设计定稿，待立项实施**（本文不含任何已实施改动）
读者：有声书/音频素材库链路的实现者与验收者
关联文档：

- [本地优先资产架构说明](LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md) — 用户侧（浏览器 vault）本地优先的既有设计，本文不重复也不改动它
- [音频素材库公网域名部署说明](AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md) — `audio.sggf.net` / 自有 OSS Bucket 的启用条件与禁止事项
- [仓库清理规则](REPOSITORY_CLEANUP_RULES_20260419.md) — §4.6 把 `audiobook_scene_runs/`、`music_cache/` 列为"可在确认后清理"，与本文 §8 风险 R3 冲突，需一并修订
- 用户资产字段契约：[User Asset Local Storage Metadata Contract](contracts/USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md)

## 0. 摘要

目标一句话：**用户可见的音频长期只存云端，服务端本地退化为可回收的缓存层，本地留哪些文件由"哪个项目在生成过程中消费过它"决定，项目删除时该项目独占的产物必须物理回收。**

结论：**方向不需要新发明，项目里已有正式设计与三套可直接复用的机制**（`LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md:14` 已把"服务端长期目录不堆用户可见大文件"写成目标；临时片段层已实现完整的 TTL + 引用判据 + 每小时 janitor）。真正要做的是补 6 个缺口（§4），按 §9 的 W0→W7 顺序落地；其中只有两条是不可调换的硬约束：**回收类改动（W5）不得早于成品建云真源（W4）**，**逐出类改动（W6）不得早于归档（W3）**。

三条必须先裁定的事（§6）：共享素材池**不随项目删除**；付费产物**先建立云真源才允许本地逐出**；`audio_library_assets.storage_mode` 与 `user_asset_records.storage_mode` **两套词表不合并**。

## 1. 目标与非目标

### 目标

1. **云为真源**：任何用户可见音频，在允许删除其服务端本地副本之前，必须已存在 `durable_cloud` 记录（`cloud_uri` + `object_key` + `sha256`）。
2. **本地即缓存**：读取路径遇到本地 miss 时能自动回源物化，而不是直接失败；缓存占用由配额 + LRU 控制。
3. **可归因**：本地每个音频文件能反查到"哪些项目/章节/run 消费过它"，项目删除时据此回收。
4. **级联回收闭合**：项目删除链路把该项目独占产物（含运行目录、场景 artifact、非镜像 staged 输出）全部物理回收。

### 非目标

- 不改动浏览器侧 local-first 资产架构（vault 三级回退、`local_mirror` 收录流程保持原样）。
- 不做按用户物理隔离的服务端目录（当前单后端实例共享一份素材池，`asset_scope` 只有 `shared_library`；"每个人本地有哪些"的用户侧语义已由 vault 承担，见 `LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md` §3）。
- 不引入第三方媒体云或转码服务。
- 不在本文档周期内执行任何删除/迁移。

## 2. 现状基线：三层，三种成熟度

| 层 | 物理目录 | 云真源 | 回源下载 | 本地回收 | 项目归属可反查 |
| --- | --- | --- | --- | --- | --- |
| 临时片段 | `backend/data/tmp/audiobook_runs/` | ✅ 驱动二选一 `temp_segment_store.py:221-225` | ✅ `load_bytes:454`、OSS 后端 `httpx.get(public_url):560` | ✅ 最完整 | ✅ `ChapterAudioRun:190/252/253` |
| 共享素材库 | `backend/data/audio_library/{sound_effects,music_cache,approved_sfx}` | ⚠️ 部分：sfx 32/32 `durable_cloud`；music 22/38；approved_sfx 0 | ❌ **模块无 download 能力**（`audio_asset_cloud_storage.py` 仅导出 upload/head/list/delete） | ⚠️ 仅管理员全局端点 `routes_audio_library.py:2185`（本地+云同删）、`:2306`（孤儿清理） | ❌ `audio_library_asset.py` 无 `project_id`/`user_id`，`asset_scope` 默认 `shared_library`（`:25`） |
| 项目产物层（用户成品 + 运行中间产物） | `backend/audiobooks/`、`backend/data/scene_audio_artifacts/`、`backend/data/audiobook_scene_runs/` | ❌ **完全没有**：`chapter_output_publish.py` 全文无云上传，`ChapterAudioOutput`/`ChapterAudio` 模型无云字段（grep `cloud\|public_url\|object_key\|storage_mode` 于 `models/audiobook.py` 零命中） | ❌ | ⚠️ 仅删 `ChapterAudio.audio_path` 镜像列（`routes_delete.py:79-114`） | ✅ `SceneAudioArtifact.stored_rel_path:405` + `audiobook_project_id:396`、`ChapterAudioOutput.audio_path:291` + `file_status:289` |

关键读取事实（决定了"本地不可删"）：

- 混音与音效解析**只认存在的本地文件**：`audio_library_paths.py:24-37`（`resolve_audio_library_file_path`）、`sound_effect_designer.py:852-876`（`_resolve_effect_audio_path`，绝对路径 / 库根相对 / `sound_effects` 按 stem `rglob`）、`_music_mixin.py:41-108`、`_sfx_mixin.py:84-102`。全链路 **0 处**从素材库 `public_url` 拉取。
- 质检必须吃本地字节：`sound_effect_designer.py:1636-1666`（pydub 响度/静音）、`:1700-1754`（ffprobe + volumedetect 兜底）、`sfx_library_downloader.py:1475-1508`。
- 唯一已有的"回源"是**给浏览器跳转**，不是服务端物化：`routes_audio_library.py:876-882`（本地缺失才 `RedirectResponse(public_url)`）。
- `audio_library_assets` 表实测 **0 行**（2026-10-11，同库 `users=5 / projects=4 / chapters=3502` 为活库对照）→ 素材库的 DB/JSON 双索引里，**只有 JSON 一份实际承载云元数据**，`POST /audio-library/db-sync`（`routes_audio_library.py:1691`）从未执行。

## 3. 2026-10-11 云端可达性实测证据

探测方式：只读 HTTPS（对象级公共读，无需签名）。**本地进程无 OSS 凭证**，`AUDIOBOOK_AUDIO_LIBRARY_OSS_*` 与 `DASHSCOPE_API_KEY` 全部 absent（仅检测存在性，未读取任何密钥文件），因此签名 `GetObject`/`PutObject`/`DeleteObject` 权限本轮**未验证**。

| 检查项 | 结果 |
| --- | --- |
| `audio.sggf.net` DNS | 解析到 `106.14.228.169` |
| `sggf-audio-library.oss-cn-shanghai.aliyuncs.com` | 解析可达，`server: AliyunOSS` |
| 索引云字段覆盖（**全量 70 条**） | sfx `32/32`、music `22/38` 为 `durable_cloud`，这 54 条的 `object_key` 与 `public_url` **全部非空**，host 全为 `audio.sggf.net` |
| **全量 HEAD（54 个云对象）** | `sfx 32/32 → 200`、`music 22/22 → 200`，Range GET 抽样 `206 / audio/mpeg`；云端声明总字节 **56.8 MB** |
| **全量 sha256 逐字节等价** | 可本地对照的 52 个对象 `MATCH=52 / DIFF=0`（同时校验字节数相等） |
| **索引有记录但本地文件已丢** | music 2 条 `durable_cloud`（Mureka，10s / 3s，`music_cache/966e863b….mp3`、`music_cache/bf3361be….mp3`）本地文件已不存在 ⇒ 云端是唯一副本，而**当前无任何代码能把它取回**，这两条配乐在混音里已不可用（G1 的现网后果） |
| 索引指纹字段（**全量 70 条**） | `sha256` 命中 **0/70** ⇒ 回源没有校验依据（G6 成立，且比初判更严重） |
| **负控制**（把末级文件名换成不存在的 key） | `404 application/xml` ⇒ 排除 CDN 恒 200 假阳性 |
| `shared/audio_library/healthcheck.txt` | `200`，正文 `ok` |
| Bucket 根路径列举 | `403` ⇒ 不可枚举，对象只能凭 key 访问 |

复现口径（本文所有云侧数字都按此得出，可重跑）：读 `sound_effects_index.json` + `music_index.json` 全量条目 → 过滤 `public_url` 非空 → `httpx` 逐条 `HEAD` 与整文件 `GET` → 按条目 `local_cache_path`（回退 `file_path`）解析本地文件 → 比对整文件 sha256 与字节数；`approved_sfx` 的引用反查取两索引 `file_path` 的 basename 集合与 `approved_sfx/` 下 1035 个文件名求交集。探测脚本为一次性只读脚本，已按项目规则删除，未落任何密钥。

结论：

1. `AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md:104` 设置的启用前置条件（DNS / HTTPS / Range / 公共读）**在生产侧已满足**，`docs/AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md:7` 的记录仍然有效。
2. `.agent/optimization-guide-ear-galaxy.md:2611`「`audio.sggf.net` 仍是无效 DNS」的结论**已过期**，后续不得再据此判定 P1 阻塞。
3. 素材库这层的云副本是**可用真源**（54/54 可达、52/52 与本地逐字节全等），不是占位对象；P0 回源与 P2 逐出在这层具备安全前提。**但注意规模**：云上素材总盘只有 56.8 MB，`approved_sfx` 的 484 MB 一个字节都不在云上（G5）。
4. 已验证的是 `shared/audio_library/*` 前缀的**公共读**；`dashscope_oss` 属供应商临时空间、生命周期不由我方控制（`AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md:8`），P0/P1 一律以 `aliyun_oss` 为准，且**禁止**把 `dashscope_oss` 对象改写到自有域名（`:105`）。P1 新增的 `audiobook/*` 前缀能否公共读**尚未验证**，见 R1。

## 4. 缺口清单

| ID | 缺口 | 证据 |
| --- | --- | --- |
| G1 | 无服务端回源下载能力 | `audio_asset_cloud_storage.py` 导出面 `:628-636` 无 download；消费侧只认本地存在文件（§2） |
| G2 | 用户成品音频完全没有云副本，真正属于用户的数据反而不在云上 | `chapter_output_publish.py`（无上传）、`models/audiobook.py`（无云列）、`audiobooks/` 与 `scene_audio_artifacts/` 均无云元数据 |
| G3 | 素材库无法按项目/用户归因 | `audio_library_asset.py` 无 `project_id`/`user_id`；上传者仅存 `metadata_json.uploaded_by_user_id`（`routes_audio_library.py:717-720`） |
| G4 | 项目删除链路漏三类物理产物 | `routes_delete.py` 对 `SceneAudioArtifact` / `scene_audio_artifacts` / `audiobook_scene_runs` **零命中**；`audiobook_scene_runs` 在全仓 `backend/app` + `scripts` 内**无任何删除代码**；非镜像 staged/superseded 仅靠**手动** `scripts/cleanup_expired_artifacts.py`（30 天、`--apply`） |
| G5 | 存在"唯一副本在本地磁盘"的资产 | 两索引 **0/70** 条有 `sha256`（§3 全量）；`music_index.json` 16/38 条无 `storage_mode`（实测本地文件 16/16 全在 ⇒ 磁盘是唯一副本）；`approved_sfx/` 1035 文件 484M **无任何云字段**，且其唯一生产读取方已停用（见下）。反向案例同样存在：2 条 `durable_cloud` 记录本地文件已丢，云端是唯一副本，而当前无代码可取回 |
| G6 | 回源缺指纹、云元数据只有一处 | 两索引 **全量 70 条 `sha256` 字段 0 命中**（§3 全量实测），回源后无从校验；`audio_library_assets` 表 0 行，DB 侧索引从未建立 |

G5 附带事实修正：`approved_sfx/` 的导入通路已关停——`POST /audio-library/sound-effects/import-manifest` 无条件抛 `410 GONE`（`routes_audio_library.py:1687-1690`），唯一读这些文件的 `SfxLibraryDownloader.import_local_assets`（`sfx_library_downloader.py:1087`）除测试外无生产调用方；`manifest-draft`（`:1617`）只把 `source_dir` 当字符串写进 manifest，不打开音频。两个索引 0 条指向 `approved_sfx`，1035 个文件按文件名反查索引 0 命中。⇒ 它是**已关停通路留下的源池 + 许可档案**，不是可用池。

## 5. 设计

### P0 · 回源下载与缓存命中（唯一硬前置）

**能力**：给素材库补"按云元数据把对象物化回本地缓存路径"，并把解析语义从"本地必须存在"改为"本地 miss 则回源"。

**现网症状（缺口已造成实际资产不可用）**：`music_index.json` 里 2 条 `durable_cloud` 的 Mureka 配乐，云端对象 HEAD 200 可取，但本地文件已丢；因为解析只认本地存在文件（`_music_mixin.py:41-108`），这两条素材现在**在索引里可见却在混音里永远拿不到**，也没有任何代码能修复它。P0 是这条路径的唯一解。

改动点：

- `audio_asset_cloud_storage.py` 新增 `download_library_object(*, object_key: str, to_local_path: Path, expected_sha256: str = "", content_type: str = "") -> Dict[str, Any]`，复用既有签名与配置读取（`_build_aliyun_oss_request_headers:245`、`_get_aliyun_oss_required_config:461`、`_build_aliyun_oss_object_url:161`），GET 流式写临时文件 + `os.replace` 原子落位。
- 新增 `ensure_library_local_cache(asset_entry) -> Path`：解析 `local_cache_path` → 存在即返回；miss 且有 `object_key` 则回源；回源后**必须**校验 sha256 与大小，不符则删临时文件并抛错。
- 接入三处解析入口（只做"miss 时多一步回源"，不改既有优先序）：`audio_library_paths.py:24-37`、`sound_effect_designer.py:852-876`、`_music_mixin.py:41-108`。

失败语义：云未配置（driver 解析失败）或对象缺失 → 保持当前行为（本地 miss 即失败），错误信息区分 `cache_miss_no_cloud_source` / `cache_miss_cloud_fetch_failed`，不得静默降级为空音频。

前置依赖：G6 —— 回源校验需要指纹，故 P0 同时补录 `sha256`（对本地缓存一次性哈希回填 JSON/DB），否则回源只能校验 Content-Length，不足以证明真源等价。

验收：本地删掉一个 `durable_cloud` 素材文件 → 触发解析 → 文件自动回源且 sha256 与索引记录一致；对无云字段对象 → 明确报 `cache_miss_no_cloud_source` 且不产生半成品文件。

### P1 · 用户成品音频建立云真源（补最大缺口）

**数据模型**：`chapter_audio_outputs`、`scene_audio_artifacts` 各加 `storage_mode` / `storage_driver` / `cloud_uri` / `object_key` / `public_url` / `local_cache_path` + `sha256`（新增 Alembic 迁移；词表**沿用 `audio_library_assets` 的 `local_cache` / `durable_cloud`**，不得借用 `user_asset_records` 的 `temp_cloud/local_mirror` 枚举 —— `LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md` §2 末尾明确"两边不要混读"）。

**object key 规范**：`audiobook/projects/{project_id}/chapters/{chapter_id}/run_{run_id}/{basename}`；场景 artifact 用 `audiobook/projects/{project_id}/scenes/{artifact_id}{ext}`。项目归属直接编码进 key，P3 的按项目回收即可凭前缀核对云端。

**上传时机**：`publish_seed_scene_chapter_output`（`chapter_output_publish.py:221`）/ `publish_legacy_chapter_output`（`:394`）事务提交**之后**投递 Celery 任务上传（遵循"commit 后才 dispatch"的既有教训），上传成功回写云字段；失败保留 `local_cache` 并计入重试，**不回滚发布状态**。

**播放与下载**：沿用素材库已有范式 —— 本地优先 `FileResponse`（`routes_download.py:243`），本地缺失时 302 到 `public_url`（对照 `routes_audio_library.py:876-882`）。前端不需要改（`frontend/src/services/api.ts:2878` 那条链保持）。`os.path.exists` 判失败的分支（`routes_download.py:160-168`）改为"缺失→有云则跳转/回源，无云才 404"。

**必须先扩权限（写与读都要）**：`AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md:98-100` 的 RAM 策略资源范围只覆盖 `sggf-audio-library/shared/audio_library/*`，P1 新前缀 `audiobook/*` 既不在写授权内（直接上传 403），其**公共读 / CDN 映射也未经验证**（§3 只证明了 `shared/audio_library/*` 可读）。302 播放链路完全依赖后者，因此 W0 必须同时验证 `audiobook/*` 的 `PutObject` 与匿名 `GET`，两项都通过才允许 P1 上线。立项另需扩 RAM 策略与 Bucket 规则，并同步修订该文档的推荐架构段落（`:16-19` 目前把"DB 只存元数据、本地仅作缓存"的范围只写在素材库语境里）。

**本地路径与回收语义**（避免 W4/W5 实施时口径漂移）：

- 成品本地落盘路径**保持现状不变**（`build_chapter_audio_output_path`，`background_jobs_shared.py:169-195`），P1 只新增云元数据列，不改目录布局；`local_cache_path` 记相对 `backend` 根的路径，与 `file_path` 一致，便于逐出后原路回源。
- 任何"本地可删"判据都必须叠加 `storage_mode == durable_cloud`：包括 `scripts/cleanup_expired_artifacts.py` 的 30 天 staged/superseded 回收、以及 P3 的项目级回收。未上云的对象一律不删。
- 逐出后的回源走 P0 同一函数（`ensure_*_local_cache` 语义在成品层对应 `ensure_chapter_output_local_cache`），不得在播放路由里各写一份下载逻辑。

验收：新生成章节 → 云字段 `durable_cloud` 且公网 `Range` 可取；人为删除本地成品 → 播放不失败（302 命中或回源命中）；`sha256` 云/本地一致；30 天回收脚本对未上云记录**跳过并计数**。

### P2 · 素材消费登记 + 配额 LRU 逐出（把"本地该留哪些"变成可查询事实）

**新表** `audio_library_asset_usages`：`asset_id`（FK `audio_library_assets`，CASCADE）、`audiobook_project_id`、`chapter_id`、`run_id`、`role`（`sfx` / `bgm` / `preview` / `asr`）、`first_seen_at`、`last_seen_at`、`hit_count`；唯一键 `(asset_id, audiobook_project_id, role)`。

**写入点**：消费即登记 —— `sound_effect_designer.py:852-876` 与 `_music_mixin.py:41-108` 解析命中处。异步、失败不阻断生成。

**回填**：`ChapterAudio.script_json` 每片段已带 `sfx_audio_path` / `bgm_audio_path` / `mix_audio_path` / `audio_chunk_cache_paths`（字段清单见 `chapter_segment_assets.py:43-54`，收集器 `:189-221`）→ 可离线回灌历史引用关系，不依赖新数据积累。

**逐出**：新增 Celery 周期任务（复用 `backend/app/celery_app.py:72-76` 的 beat 写法），判据完全照抄临时片段层已验证的两步式：先按 DB 记录筛候选（`storage_mode=durable_cloud` 且 `sha256` 已录 且 `last_seen_at` 超阈值），再删本地文件、**保留 DB/JSON/云元数据**。配额键 `AUDIOBOOK_AUDIO_LIBRARY_LOCAL_QUOTA_MB`，LRU 逐出至阈值以下。

**边界**：逐出对象仅限共享素材缓存；正在被活跃 run 引用的路径不得逐出（判据复用 `scripts/cleanup_expired_artifacts.py:66-99` 的"同一路径是否被其他登记引用"检查）。

### P3 · 项目级联回收闭合（对应任务 #62）

`routes_delete.py:286-304` 的 `delete_files=True` 分支补三块 + 一处计数：

1. `scene_audio_artifacts/` 物理文件 + `SceneAudioArtifact` 行（按 `stored_rel_path` 枚举，删除前先判该路径是否仍被其他登记引用）。
2. `audiobook_scene_runs/{task_id}/` 整个运行目录（`_scene_render_mixin.py:270-277` 写入，全仓当前无人删）。
3. 非 `ChapterAudio.audio_path` 镜像的 `ChapterAudioOutput`（staged / superseded）文件，把 `scripts/cleanup_expired_artifacts.py` 的 30 天判据提为周期任务并统一 `file_status='purged'` 墓碑语义（`:195-210`），不再依赖手动 CLI。**30 天判据必须叠加 `storage_mode == durable_cloud`**：scene artifact 与 scene runs 同理，未建立云真源前一律不物理删（P1 回收语义）。
4. P2 引用计数递减（仅在 P2 上线后）。

**禁止**：项目删除**不得**删除共享素材本体，也不得调用 `delete_audio_library_object`（`routes_delete.py` 现在也不该引入它）—— 理由见 §6 裁定一。

验收：造一个含场景模式的项目 → 生成 → 删除项目 → 该项目的 `audiobooks/`、`scene_audio_artifacts/`、`audiobook_scene_runs/` 文件与 DB 行全部消失，`audio_library/` 池文件计数不变，`git status` 无涉及受保护目录的变更。

## 6. 三条必须先裁定的设计点

**裁定一（推荐已定）：共享素材不随项目删除，本地占用由"配额 + LRU"控制。**
`approved_sfx` / `sound_effects` / `music_cache` 是全局池（`asset_scope=shared_library`），多项目共用。若"项目删除"级联删共享素材，任何单项目删除都会带走其他项目的依赖。正确语义：项目删除只递减引用计数；逐出只在配额压力下发生，且只逐 `durable_cloud` 的对象。

**裁定二（推荐已定）：付费产物必须先建立云真源，才允许被任何"本地可清"自动化触碰。**
`music_cache/` 是 Mureka / 豆包付费合成结果，其中 16/38 索引记录连云字段都没有、`audio_library_assets` 表 0 行 ⇒ 磁盘文件是**唯一副本**。同理 `approved_sfx/` 1035 文件（484M）从未上云。在这批对象完成归档上传之前，任何自动逐出都构成不可逆资产损失。归档是一次性动作，走 dry-run/confirm；现有 `cloud-sync` 端点只扫 `sound_effects_index.json` / `music_index.json`（`routes_audio_library.py:1777-1780`），覆盖不到 `approved_sfx`，需要一次性脚本或扩端点扫描范围。

**裁定三（推荐已定）：两套 `storage_mode` 词表不合并。**
`audio_library_assets` 用 `local_cache` / `durable_cloud`；`user_asset_records` 用 `temp_cloud` / `durable_cloud` / `local_mirror` / `local_only`。同名不同义已被显式警告（`LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md` §2）。P1 新列表述沿用前者。若将来要把章节成品登记成用户资产，走 `local_mirror` 收录链路（§5 表格"Audiobook 章节成品手动收录"），不要在服务端表上发明新枚举。

## 7. 可直接复用的既有机制（不重新发明）

| 需求 | 现成实现 |
| --- | --- |
| TTL + 引用判据 + 周期清理范式 | `temp_segment_janitor.py:128-165`（先 `repository.py:1115-1130` 按 `expires_at & resumable` 筛 DB，再按 `checkpoint_json.cached_audio_paths` / `segments[*].temp_object_key` 删物理文件）、`celery_app.py:72-76` |
| "同一路径是否仍被其他登记引用"判据 | `scripts/cleanup_expired_artifacts.py:66-99` |
| 云对象存在性批量核对 / 云端垃圾清理（均 dry-run+confirm） | `routes_audio_library.py:1959`（`cloud-check`）、`:2045`（`cloud-cleanup`） |
| 本地优先、缺失跳云的播放范式 | `routes_audio_library.py:876-882` |
| 纯云试听缓存（无本地目录）范式 | `tts_preview_cache.py:138-240`（HEAD 命中返 CDN URL，未命中合成后上传，临时文件 finally 即删） |
| 用户侧本地副本生命周期 | `user_asset_records.storage_mode` + `frontend/src/utils/localAssetVault.ts`（本文不动） |

## 8. 风险与未决

- **R1 凭证面与新前缀读权限未验证**：本地无 OSS AK（环境变量全 absent），签名 `GetObject/PutObject/DeleteObject` 均未实测（§3）；§3 证明的只是 `shared/audio_library/*` 的**匿名可读**，P1 的 `audiobook/*` 前缀既无写授权、也无公共读证据，两者都要在服务器环境补验，验证时按既有规则只打印变量名与存在性。
- **R2 逐出与质检耦合**：pydub/ffprobe 质检需本地字节（`sound_effect_designer.py:1636-1666`、`:1700-1754`）。P2 逐出后再次质检会触发回源，需确保回源在质检路径可达（不能只挂在混音路径上）。
- **R3 文档与事实冲突**：`REPOSITORY_CLEANUP_RULES_20260419.md:263-264` 把 `audiobook_scene_runs/` 与 `music_cache/` 归入"测试与运行生成目录，本地文件可在确认后清理"（`:272`）。在 `music_cache` 存在唯一副本（G5）的事实下，这条规则会直接指导人删掉不可复生的付费产物，P2 落地时必须同步改写该节，把"可清"限定为"已有 `durable_cloud` + `sha256` 的对象"。
- **R4 双索引长期分叉**：DB 表 0 行、JSON 承载全部云元数据（§2）。若 P2/P3 建在 DB 上而 `db-sync`（`routes_audio_library.py:1691`）仍不执行，会出现"表里有素材行、JSON 里才有云字段"的分裂。P1 前需先跑一次 `db-sync` 并让 JSON 退为兼容读路径。
- **R5 单实例假设**：本设计假设后端单实例共享一份本地池。若将来横向扩容，逐出与回源会互相抖动，需要改为按实例独立缓存 + 无共享状态假设（届时 P2 的配额语义要重新定义）。
- **R6 CDN 计费与缓存**：对象为公共读、可凭 key 直取，Bucket 不可枚举（§3）。成品上云后播放流量会从后端 `FileResponse` 迁到 CDN，需要评估 `audio.sggf.net` 的 CDN 计费与 Range 支持已验证（§3）之外的缓存刷新策略。
- **R7 `approved_sfx` 归档后的语义**（W3 必须先定，否则 W6 配额池会把它算进去）：归档动作**不得**把它写进 `sound_effects_index.json` / `music_index.json`，也不得创建 `audio_library_assets` 行 —— 那条池已被 410 关停（§4 附注），进索引就等于把不可用素材重新暴露给混音。正确形态是独立归档前缀 `shared/audio_library/archive/approved_sfx/...` + 一份 ledger（沿用 manifest 的 `license` / `source_url` / `license_checked_at` 字段），只服务"重新开池时复用人工核许可成果"与留证。因此它不参与 P2 逐出配额，也不由项目删除触达。
- **未决 U1**：`approved_sfx` 484M 归档后是否长期保留 —— 留证价值由用户裁定，本设计只负责把它变成云上归档，不预设删除。

## 9. 立项拆分建议

| 序号 | 工作包 | 依赖 | 规模 | 完成判据 |
| --- | --- | --- | --- | --- |
| W0 | RAM 策略与 Bucket 扩 `audiobook/*` 前缀；**验证该前缀的 `PutObject` 与匿名 `GET`**；在有凭证的服务器环境补验签名调用 | — | 小（运维） | 写授权 + 匿名读 200/206 各实测成功；只打印变量名与存在性 |
| W1 | G6 指纹回填：**全量 70 条**索引条目补 `sha256`（含本地缺失 2 条从云端回源后再录） | — | 小 | 两索引 `sha256` 命中率 70/70；复现 §3 方法得到 `MATCH=全部可对照条目 / DIFF=0` |
| W1b | 执行 `POST /audio-library/db-sync`（`routes_audio_library.py:1691`）建立 DB 侧素材索引，JSON 退为兼容读路径（R4） | W1 | 小 | `audio_library_assets` 行数与索引条目一致，云字段在 DB 可见 |
| W2 | P0 回源下载 + `ensure_library_local_cache` + 三处解析接入 | W1、W1b | 中（含 TDD） | §5 P0 验收全部通过（含现网那 2 条本地已丢的配乐可自动回源并重新可用） |
| W3 | G5 归档：`music_cache` 16 条无云字段记录 + `approved_sfx` 1035 文件上云（dry-run/confirm 两段），按 R7 只进归档前缀不入索引 | W0、W1 | 中 | 归档后每条 `durable_cloud` 且可回源校验；两索引条目数与 `audio_library_assets` 行数**不因归档而增加** |
| W4 | P1 成品上云（迁移 + 发布后异步上传 + 播放 302/回源） | W0、W2 | 大 | §5 P1 验收；全量回归串行绿 |
| W5 | P3 级联回收闭合（#62） | **W4（硬约束，不得早于）** | 中 | §5 P3 验收；回收判据全部叠加 `durable_cloud` |
| W6 | P2 消费登记 + 配额 LRU 逐出 | W2、W3、W4 | 大 | 逐出后自动回源、活跃引用不被逐出、配额可控、归档前缀不参与逐出池 |
| W7 | 文档收口：修订 `AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md`（推荐架构范围与新前缀）、`REPOSITORY_CLEANUP_RULES` §4.6（R3）、`LOCAL_FIRST` §5 模块表现状 | W2–W6 | 小 | 三处口径与代码事实一致 |

推荐执行序：**W0 → W1 → W1b → W2 → W3 → W4 → W5 → W6 → W7**。

两条排序理由，实施时不得调换：

1. **W3 提前到 W4 之前**：`music_cache` 那 16 条与 `approved_sfx` 现在都是"磁盘唯一副本"，归档不依赖成品链路，早做能直接缩短不可逆风险敞口。
2. **W5 不早于 W4**：`scene_audio_artifacts/` 与 `audiobook_scene_runs/` 目前完全没有云副本，在真源建立前实现"删除项目即物理回收"，等于把用户唯一副本删掉 —— 违反裁定二。这是全文唯一的硬顺序约束。

## 10. 事实源索引

| 事实 | 位置 |
| --- | --- |
| 服务端长期目录不堆用户可见大文件（目标句） | `LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md:14` |
| 两套 `storage_mode` 不得混读 | 同上 §2 末段 |
| 本地仅作导入暂存 / 质检 / 混音缓存 | `AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md:19` |
| DNS/HTTPS/Range 启用前置 | 同上 `:39-54`、禁止事项 `:102-108` |
| RAM 资源范围仅 `shared/audio_library/*` | 同上 `:98-100` |
| 云模块能力面（无 download） | `audio_asset_cloud_storage.py:628-636` |
| driver 解析与 local_cache 兜底 | 同上 `:33-58`、`:596-615` |
| 上传后本地仍为读取源 | 同上 `:583-588`（docstring） |
| 素材表无归属字段 | `audio_library_asset.py:23-74`、`routes_audio_library.py:717-720` |
| 导入端点 410 关停 | `routes_audio_library.py:1687-1690` |
| 唯一读 `approved_sfx` 的函数无生产调用方 | `sfx_library_downloader.py:1087`（调用方仅 `test_sfx_library_downloader.py`） |
| 混音本地解析三处 | `audio_library_paths.py:24-37`、`sound_effect_designer.py:852-876`、`_music_mixin.py:41-108` |
| 播放 302 回源范式 | `routes_audio_library.py:876-882` |
| 片段层 TTL + 引用判据 janitor | `temp_segment_janitor.py:128-203`、`repository.py:1115-1130`、`celery_app.py:72-76` |
| 项目删除已覆盖/未覆盖 | `routes_delete.py:101-131`、`:286-304`（对 scene artifact / scene runs 零命中） |
| 手动 30 天回收脚本与引用判据 | `scripts/cleanup_expired_artifacts.py:46`、`:66-99`、`:195-210` |
| 片段路径→项目 可反查字段 | `models/audiobook.py:190/252/253`（run）、`:289-291`（output）、`:396-406`（scene artifact）、`chapter_segment_assets.py:43-54` |
| 清理规则与事实冲突条目 | `REPOSITORY_CLEANUP_RULES_20260419.md:263-264`、`:272` |
| 「audio.sggf.net 无效 DNS」过期记录 | `.agent/optimization-guide-ear-galaxy.md:2611`（已被 §3 实测推翻） |
