"""add cascade delete constraints to audiobook models

Revision ID: add_cascade_delete_constraints
Revises: d1d5ec080e06
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_cascade_delete_constraints'
down_revision = 'd1d5ec080e06'
branch_labels = None
depends_on = None


def upgrade():
    # 修改 audiobook_projects.project_id 外键，添加 CASCADE
    op.drop_constraint('audiobook_projects_project_id_fkey', 'audiobook_projects', type_='foreignkey')
    op.create_foreign_key(
        'audiobook_projects_project_id_fkey',
        'audiobook_projects', 'projects',
        ['project_id'], ['id'],
        ondelete='CASCADE'
    )

    # 修改 chapter_audios.audiobook_project_id 外键，添加 CASCADE
    op.drop_constraint('chapter_audios_audiobook_project_id_fkey', 'chapter_audios', type_='foreignkey')
    op.create_foreign_key(
        'chapter_audios_audiobook_project_id_fkey',
        'chapter_audios', 'audiobook_projects',
        ['audiobook_project_id'], ['id'],
        ondelete='CASCADE'
    )

    # 修改 chapter_audios.chapter_id 外键，添加 CASCADE
    op.drop_constraint('chapter_audios_chapter_id_fkey', 'chapter_audios', type_='foreignkey')
    op.create_foreign_key(
        'chapter_audios_chapter_id_fkey',
        'chapter_audios', 'chapters',
        ['chapter_id'], ['id'],
        ondelete='CASCADE'
    )

    # 修改 audiobook_tasks.audiobook_project_id 外键，添加 CASCADE
    op.drop_constraint('audiobook_tasks_audiobook_project_id_fkey', 'audiobook_tasks', type_='foreignkey')
    op.create_foreign_key(
        'audiobook_tasks_audiobook_project_id_fkey',
        'audiobook_tasks', 'audiobook_projects',
        ['audiobook_project_id'], ['id'],
        ondelete='CASCADE'
    )

    # 修改 audiobook_tasks.chapter_id 外键，添加 CASCADE
    op.drop_constraint('audiobook_tasks_chapter_id_fkey', 'audiobook_tasks', type_='foreignkey')
    op.create_foreign_key(
        'audiobook_tasks_chapter_id_fkey',
        'audiobook_tasks', 'chapters',
        ['chapter_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade():
    # 回退：移除 CASCADE
    op.drop_constraint('audiobook_projects_project_id_fkey', 'audiobook_projects', type_='foreignkey')
    op.create_foreign_key(
        'audiobook_projects_project_id_fkey',
        'audiobook_projects', 'projects',
        ['project_id'], ['id']
    )

    op.drop_constraint('chapter_audios_audiobook_project_id_fkey', 'chapter_audios', type_='foreignkey')
    op.create_foreign_key(
        'chapter_audios_audiobook_project_id_fkey',
        'chapter_audios', 'audiobook_projects',
        ['audiobook_project_id'], ['id']
    )

    op.drop_constraint('chapter_audios_chapter_id_fkey', 'chapter_audios', type_='foreignkey')
    op.create_foreign_key(
        'chapter_audios_chapter_id_fkey',
        'chapter_audios', 'chapters',
        ['chapter_id'], ['id']
    )

    op.drop_constraint('audiobook_tasks_audiobook_project_id_fkey', 'audiobook_tasks', type_='foreignkey')
    op.create_foreign_key(
        'audiobook_tasks_audiobook_project_id_fkey',
        'audiobook_tasks', 'audiobook_projects',
        ['audiobook_project_id'], ['id']
    )

    op.drop_constraint('audiobook_tasks_chapter_id_fkey', 'audiobook_tasks', type_='foreignkey')
    op.create_foreign_key(
        'audiobook_tasks_chapter_id_fkey',
        'audiobook_tasks', 'chapters',
        ['chapter_id'], ['id']
    )
