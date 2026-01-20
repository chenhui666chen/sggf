-- PostgreSQL初始化脚本
-- 用于优化生产环境数据库性能

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- 用于全文搜索
CREATE EXTENSION IF NOT EXISTS "btree_gin";  -- 用于GIN索引优化

-- 配置性能参数（注意：这些参数需要在postgresql.conf中设置）
-- 这里只是示例，实际生产环境应根据服务器配置调整

-- 创建索引优化查询性能
-- 注意：这些索引会在表创建后自动创建，这里只是示例

-- 设置时区
SET timezone = 'UTC';

-- 启用查询计划统计
SET track_counts = on;

-- 设置工作内存（每个查询）
SET work_mem = '4MB';

-- 设置维护工作内存
SET maintenance_work_mem = '64MB';

-- 设置随机页面成本（用于SSD优化）
SET random_page_cost = 1.1;

-- 设置有效IO并发
SET effective_io_concurrency = 200;

-- 设置默认统计目标
SET default_statistics_target = 100;

-- 记录初始化完成
DO $$
BEGIN
    RAISE NOTICE 'PostgreSQL初始化脚本执行完成';
END $$;
