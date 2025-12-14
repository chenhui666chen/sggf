"""
添加拆书工具数据表

Revision ID: add_book_parser_tables
Create Date: 2024-12-14
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_book_parser_tables'
down_revision = None  # 需要根据实际情况设置
branch_labels = None
depends_on = None


def upgrade():
    """创建拆书工具相关表"""
    
    # 1. 创建 book_sources 表（原书来源）
    op.create_table(
        'book_sources',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        
        # 书籍基本信息
        sa.Column('title', sa.String(255), nullable=False, comment='书名'),
        sa.Column('author', sa.String(200), nullable=True, comment='作者'),
        sa.Column('isbn', sa.String(20), nullable=True, comment='ISBN'),
        sa.Column('publisher', sa.String(200), nullable=True, comment='出版社'),
        sa.Column('publish_year', sa.Integer(), nullable=True, comment='出版年份'),
        sa.Column('genre', sa.String(100), nullable=True, comment='类型/题材'),
        sa.Column('description', sa.Text(), nullable=True, comment='书籍简介'),
        sa.Column('cover_url', sa.String(500), nullable=True, comment='封面URL'),
        
        # 来源信息
        sa.Column('source_type', sa.String(20), default='text', comment='来源类型'),
        sa.Column('file_path', sa.String(500), nullable=True, comment='文件存储路径'),
        sa.Column('original_url', sa.String(1000), nullable=True, comment='原始URL'),
        
        # 统计信息
        sa.Column('total_words', sa.Integer(), default=0, comment='总字数'),
        sa.Column('total_chapters', sa.Integer(), default=0, comment='总章节数'),
        sa.Column('total_volumes', sa.Integer(), default=0, comment='总卷数'),
        
        # 解析状态
        sa.Column('status', sa.String(20), default='pending', comment='解析状态'),
        sa.Column('parse_progress', sa.Integer(), default=0, comment='解析进度0-100'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        
        # 关联项目
        sa.Column('imported_project_id', sa.Integer(), 
                  sa.ForeignKey('projects.id', ondelete='SET NULL'), 
                  nullable=True, comment='导入后创建的项目ID'),
        
        # 时间戳
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, 
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('parsed_at', sa.DateTime(timezone=True), nullable=True, comment='解析完成时间'),
    )
    
    # 2. 创建 book_chapters 表（原书章节）
    op.create_table(
        'book_chapters',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('book_id', sa.Integer(), 
                  sa.ForeignKey('book_sources.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        
        # 章节信息
        sa.Column('chapter_number', sa.Integer(), nullable=False, comment='章节序号'),
        sa.Column('title', sa.String(255), nullable=False, comment='章节标题'),
        sa.Column('content', sa.Text(), nullable=True, comment='章节内容'),
        sa.Column('word_count', sa.Integer(), default=0, comment='字数'),
        
        # 卷/部信息
        sa.Column('volume_number', sa.Integer(), nullable=True, comment='卷号'),
        sa.Column('volume_title', sa.String(255), nullable=True, comment='卷标题'),
        sa.Column('part_number', sa.Integer(), nullable=True, comment='部号'),
        sa.Column('part_title', sa.String(255), nullable=True, comment='部标题'),
        
        # 章节类型
        sa.Column('chapter_type', sa.String(20), default='normal', 
                  comment='章节类型: normal/prologue/epilogue/extra/interlude'),
        
        # 原文位置
        sa.Column('start_position', sa.Integer(), nullable=True, comment='原文起始位置'),
        sa.Column('end_position', sa.Integer(), nullable=True, comment='原文结束位置'),
        
        # 分析结果缓存
        sa.Column('summary', sa.Text(), nullable=True, comment='章节摘要'),
        sa.Column('key_events', sa.Text(), nullable=True, comment='关键事件(JSON)'),
        sa.Column('appearing_characters', sa.Text(), nullable=True, comment='出场人物(JSON)'),
        
        # 时间戳
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # 3. 创建 book_analyses 表（分析结果）
    op.create_table(
        'book_analyses',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('book_id', sa.Integer(), 
                  sa.ForeignKey('book_sources.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        
        # 分析类型和内容
        sa.Column('analysis_type', sa.String(30), nullable=False, 
                  comment='分析类型: characters/worldview/plot/style/concepts/summary/themes'),
        sa.Column('content', sa.Text(), nullable=False, comment='分析结果(JSON)'),
        
        # 质量评估
        sa.Column('confidence', sa.Float(), default=0.8, comment='置信度0-1'),
        sa.Column('completeness', sa.Float(), default=0.8, comment='完整度0-1'),
        
        # 分析范围
        sa.Column('chapter_range_start', sa.Integer(), nullable=True, comment='分析起始章节'),
        sa.Column('chapter_range_end', sa.Integer(), nullable=True, comment='分析结束章节'),
        
        # 元数据
        sa.Column('metadata', sa.Text(), nullable=True, comment='额外元数据(JSON)'),
        sa.Column('model_used', sa.String(50), nullable=True, comment='使用的AI模型'),
        sa.Column('version', sa.Integer(), default=1, comment='版本号'),
        
        # 时间戳
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, 
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # 创建索引
    op.create_index('ix_book_chapters_book_chapter', 'book_chapters', ['book_id', 'chapter_number'])
    op.create_index('ix_book_analyses_book_type', 'book_analyses', ['book_id', 'analysis_type'])


def downgrade():
    """删除拆书工具相关表"""
    op.drop_index('ix_book_analyses_book_type', 'book_analyses')
    op.drop_index('ix_book_chapters_book_chapter', 'book_chapters')
    op.drop_table('book_analyses')
    op.drop_table('book_chapters')
    op.drop_table('book_sources')
