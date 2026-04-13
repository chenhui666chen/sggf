"""normalize character story fields

Revision ID: normalize_character_story_fields
Revises: add_character_role_position
Create Date: 2026-04-08

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "normalize_character_story_fields"
down_revision = "add_character_role_position"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "role" not in existing_columns or "role_position" not in existing_columns:
        return

    op.execute(
        sa.text(
            """
            UPDATE characters
            SET role_position = CASE
                WHEN role_position IS NULL OR TRIM(role_position) = '' THEN CASE
                    WHEN LOWER(TRIM(COALESCE(role, ''))) IN ('protagonist', 'protagonist_side') THEN '主角'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) IN ('antagonist', 'antagonist_side') THEN '对手'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'deuteragonist' THEN '核心配角'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) IN ('supporting', 'supporting_role') THEN '支持角色'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'ally' THEN '盟友'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'mentor' THEN '导师'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'mentor/ally' THEN '导师型盟友'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'victim' THEN '受害者'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'victim/ally' THEN '受害者型盟友'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'guardian' THEN '守护者'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'neutral' THEN '中立角色'
                    WHEN LOWER(TRIM(COALESCE(role, ''))) = 'ambiguous' THEN '摇摆角色'
                    WHEN role = '主角方' THEN '主角'
                    WHEN role = '反派方' THEN '对手'
                    WHEN role = '中立方' THEN '中立角色'
                    WHEN role = '亦正亦邪' THEN '摇摆角色'
                    ELSE role_position
                END
                WHEN LOWER(TRIM(role_position)) = 'protagonist' THEN '主角'
                WHEN LOWER(TRIM(role_position)) = 'protagonist_side' THEN '主角'
                WHEN LOWER(TRIM(role_position)) = 'antagonist' THEN '对手'
                WHEN LOWER(TRIM(role_position)) = 'antagonist_side' THEN '对手'
                WHEN LOWER(TRIM(role_position)) = 'deuteragonist' THEN '核心配角'
                WHEN LOWER(TRIM(role_position)) IN ('supporting', 'supporting_role') THEN '支持角色'
                WHEN LOWER(TRIM(role_position)) = 'ally' THEN '盟友'
                WHEN LOWER(TRIM(role_position)) = 'mentor' THEN '导师'
                WHEN LOWER(TRIM(role_position)) = 'mentor/ally' THEN '导师型盟友'
                WHEN LOWER(TRIM(role_position)) = 'victim' THEN '受害者'
                WHEN LOWER(TRIM(role_position)) = 'victim/ally' THEN '受害者型盟友'
                WHEN LOWER(TRIM(role_position)) = 'guardian' THEN '守护者'
                WHEN LOWER(TRIM(role_position)) = 'neutral' THEN '中立角色'
                WHEN LOWER(TRIM(role_position)) = 'ambiguous' THEN '摇摆角色'
                WHEN role_position = '主角方' THEN '主角'
                WHEN role_position = '反派方' THEN '对手'
                WHEN role_position = '中立方' THEN '中立角色'
                WHEN role_position = '亦正亦邪' THEN '摇摆角色'
                ELSE role_position
            END
            WHERE role_position IS NULL
               OR TRIM(role_position) = ''
               OR LOWER(TRIM(role_position)) IN (
                    'protagonist',
                    'protagonist_side',
                    'antagonist',
                    'antagonist_side',
                    'deuteragonist',
                    'supporting',
                    'supporting_role',
                    'ally',
                    'mentor',
                    'mentor/ally',
                    'victim',
                    'victim/ally',
                    'guardian',
                    'neutral',
                    'ambiguous'
               )
               OR role_position IN ('主角方', '反派方', '中立方', '亦正亦邪')
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE characters
            SET role = CASE
                WHEN LOWER(TRIM(COALESCE(role, ''))) IN ('protagonist', 'protagonist_side') THEN '主角方'
                WHEN LOWER(TRIM(COALESCE(role, ''))) IN ('antagonist', 'antagonist_side') THEN '反派方'
                WHEN LOWER(TRIM(COALESCE(role, ''))) = 'neutral' THEN '中立方'
                WHEN LOWER(TRIM(COALESCE(role, ''))) = 'ambiguous' THEN '亦正亦邪'
                WHEN LOWER(TRIM(COALESCE(role, ''))) IN ('deuteragonist', 'ally', 'mentor', 'mentor/ally', 'guardian', 'victim/ally') THEN '主角方'
                WHEN LOWER(TRIM(COALESCE(role, ''))) = 'victim' THEN '中立方'
                WHEN LOWER(TRIM(COALESCE(role, ''))) IN ('supporting', 'supporting_role') THEN NULL
                WHEN role LIKE '%亦正亦邪%' THEN '亦正亦邪'
                WHEN role LIKE '%中立%' OR role LIKE '%旁观%' OR role LIKE '%游离%' THEN '中立方'
                WHEN role LIKE '%对手%' OR role LIKE '%反派%' OR role LIKE '%敌%' OR role LIKE '%宿敌%' OR role LIKE '%追杀者%' THEN '反派方'
                WHEN role LIKE '%主角%' OR role LIKE '%盟友%' OR role LIKE '%导师%' OR role LIKE '%同伴%' OR role LIKE '%队友%' OR role LIKE '%助力%' OR role LIKE '%守护%' THEN '主角方'
                WHEN role LIKE '%支持角色%' OR role LIKE '%核心配角%' OR role LIKE '%配角%' THEN NULL
                WHEN (role IS NULL OR TRIM(role) = '') AND (
                    LOWER(TRIM(COALESCE(role_position, ''))) IN ('protagonist', 'protagonist_side', 'deuteragonist', 'ally', 'mentor', 'mentor/ally', 'guardian', 'victim/ally')
                    OR role_position LIKE '%主角%'
                    OR role_position LIKE '%盟友%'
                    OR role_position LIKE '%导师%'
                    OR role_position LIKE '%同伴%'
                    OR role_position LIKE '%队友%'
                    OR role_position LIKE '%助力%'
                    OR role_position LIKE '%守护%'
                ) THEN '主角方'
                WHEN (role IS NULL OR TRIM(role) = '') AND (
                    LOWER(TRIM(COALESCE(role_position, ''))) IN ('antagonist', 'antagonist_side')
                    OR role_position LIKE '%对手%'
                    OR role_position LIKE '%反派%'
                    OR role_position LIKE '%敌%'
                    OR role_position LIKE '%宿敌%'
                    OR role_position LIKE '%追杀者%'
                ) THEN '反派方'
                WHEN (role IS NULL OR TRIM(role) = '') AND (
                    LOWER(TRIM(COALESCE(role_position, ''))) IN ('neutral', 'victim')
                    OR role_position LIKE '%中立%'
                    OR role_position LIKE '%旁观%'
                    OR role_position LIKE '%游离%'
                    OR role_position LIKE '%受害者%'
                ) THEN '中立方'
                WHEN (role IS NULL OR TRIM(role) = '') AND (
                    LOWER(TRIM(COALESCE(role_position, ''))) = 'ambiguous'
                    OR role_position LIKE '%亦正亦邪%'
                    OR role_position LIKE '%摇摆%'
                ) THEN '亦正亦邪'
                ELSE role
            END
            WHERE role IS NOT NULL OR role_position IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    # 数据归一化迁移不做反向回滚，避免把已规范化的数据重新污染。
    return
