# -*- coding: utf-8 -*-
"""调用方 API Key 发卡/吊销 CLI。

用法：
    python -m router_gateway.admin.client create --name 合作方甲
    python -m router_gateway.admin.client disable --id <client_id>
    python -m router_gateway.admin.client disable --id <client_id>

数据库地址取 ROUTER_GATEWAY_DATABASE_URL；执行前幂等建表，空库可直接发卡。
不提供 HTTP 管理端点（W2 明确不做）。
"""
from __future__ import annotations

import argparse
import secrets
import sys

from ..db import JobRepository, get_engine, make_session_factory
from ..db.init_db import init_schema, resolve_database_url


def generate_api_key() -> str:
    """生成随机调用方 key（URL-safe 字符集，无空格，约 43 字符）。"""
    return secrets.token_urlsafe(32)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m router_gateway.admin.client",
        description="调用方 API Key 发卡/吊销")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="登记新调用方并生成随机 key")
    p_create.add_argument("--name", required=True,
                          help="调用方名称（仅管理用途）")

    p_disable = sub.add_parser("disable", help="吊销调用方（该 key 立即 401）")
    p_disable.add_argument("--id", dest="client_id", required=True,
                           help="发卡时输出的 client id；不要在命令行传递 API Key")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    engine = get_engine(resolve_database_url())
    try:
        # 幂等自举：库已由 W1 初始化时这里无副作用；全新空库也可直接发卡
        init_schema(engine)
        repo = JobRepository(make_session_factory(engine))

        if args.command == "create":
            client = repo.create_client(name=args.name,
                                        api_key=generate_api_key())
            # name 置末：允许名称含空格；api_key 字符集保证无空格
            print(f"id={client.id} api_key={client.issued_api_key} "
                  f"name={client.name}")
            return 0

        if not repo.disable_client(args.client_id):
            print(f"未找到 id={args.client_id} 对应的 client", file=sys.stderr)
            return 1
        print(f"已吊销 client：id={args.client_id}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
