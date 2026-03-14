"""
SQL 安全验证模块
防止 SQL 注入和危险操作
"""
import re
from typing import Tuple, List


class SQLSecurityError(Exception):
    """SQL 安全异常"""
    pass


class SQLValidator:
    """SQL 查询安全验证器"""
    
    # 禁止的危险操作关键字
    FORBIDDEN_KEYWORDS = [
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 
        'CREATE', 'ALTER', 'TRUNCATE', 'REPLACE',
        'GRANT', 'REVOKE', 'LOCK', 'UNLOCK',
        'CALL', 'EXEC', 'EXECUTE',
        'LOAD_FILE', 'INTO OUTFILE', 'INTO DUMPFILE',
        'BENCHMARK', 'SLEEP', 'WAITFOR',
        'COMMIT', 'ROLLBACK', 'SAVEPOINT',
        'SET PASSWORD', 'SET GLOBAL', 'SET SESSION',
    ]
    
    # 允许的查询操作
    ALLOWED_OPERATIONS = ['SELECT', 'SHOW', 'EXPLAIN', 'DESCRIBE', 'DESC']
    
    # 敏感字段（用于脱敏）
    SENSITIVE_FIELDS = [
        'password', 'password_hash', 'password_reset',
        'email', 'phone', 'mobile', 'telephone',
        'id_card', 'identity', 'social_security',
        'credit_card', 'bank_card', 'account_number',
        'token', 'api_key', 'secret', 'private_key',
        'address', 'ip_address', 'mac_address'
    ]
    
    # 最大查询行数限制
    MAX_QUERY_ROWS = 1000
    
    # 查询超时时间（毫秒）
    QUERY_TIMEOUT_MS = 5000
    
    @classmethod
    def validate(cls, sql: str) -> Tuple[bool, str]:
        """
        验证 SQL 查询是否安全
        
        Args:
            sql: SQL 查询语句
            
        Returns:
            (is_safe, error_message)
        """
        if not sql or not sql.strip():
            return False, "SQL 查询不能为空"
        
        # 移除注释和字符串内容，避免误判
        cleaned_sql = cls._clean_sql(sql)
        upper_sql = cleaned_sql.upper()
        
        # 1. 检查是否包含禁止的关键字
        for keyword in cls.FORBIDDEN_KEYWORDS:
            if keyword in upper_sql:
                return False, f"不允许的操作：{keyword}"
        
        # 2. 检查是否以允许的操作开头
        is_allowed = any(
            upper_sql.strip().startswith(op) 
            for op in cls.ALLOWED_OPERATIONS
        )
        if not is_allowed:
            return False, "只允许执行 SELECT 查询操作"
        
        # 3. 检查是否包含多个语句（防止分号注入）
        statements = [s.strip() for s in cleaned_sql.split(';') if s.strip()]
        if len(statements) > 1:
            return False, "不允许执行多个语句"
        
        # 4. 检查是否有 LIMIT 限制（防止全表扫描）
        if 'SELECT' in upper_sql and 'LIMIT' not in upper_sql:
            # 自动添加 LIMIT
            sql = cls._add_limit(sql, cls.MAX_QUERY_ROWS)
        
        # 5. 检查注释中是否包含危险内容
        if cls._has_dangerous_comments(sql):
            return False, "注释中包含可疑内容"
        
        return True, sql
    
    @classmethod
    def _clean_sql(cls, sql: str) -> str:
        """
        清理 SQL，移除注释和字符串内容
        
        Args:
            sql: 原始 SQL
            
        Returns:
            清理后的 SQL
        """
        # 移除单行注释 --
        sql = re.sub(r'--.*?(\n|$)', '', sql)
        
        # 移除多行注释 /* */
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        
        # 移除字符串内容（避免误判）
        sql = re.sub(r"'[^']*'", "''", sql)
        sql = re.sub(r'"[^"]*"', '""', sql)
        
        return sql
    
    @classmethod
    def _add_limit(cls, sql: str, limit: int) -> str:
        """
        为查询添加 LIMIT 限制
        
        Args:
            sql: SQL 查询
            limit: 限制行数
            
        Returns:
            添加 LIMIT 后的 SQL
        """
        # 简单的实现：在末尾添加 LIMIT
        # 注意：对于复杂查询（如 UNION、子查询）可能需要更复杂的处理
        sql = sql.rstrip().rstrip(';')
        return f"{sql} LIMIT {limit}"
    
    @classmethod
    def _has_dangerous_comments(cls, sql: str) -> bool:
        """
        检查注释中是否包含危险内容
        
        Args:
            sql: SQL 查询
            
        Returns:
            是否包含危险内容
        """
        # 提取注释
        comments = re.findall(r'--.*$', sql, re.MULTILINE)
        comments += re.findall(r'/\*.*?\*/', sql, re.DOTALL)
        
        for comment in comments:
            upper_comment = comment.upper()
            for keyword in cls.FORBIDDEN_KEYWORDS:
                if keyword in upper_comment:
                    return True
        
        return False
    
    @classmethod
    def should_mask_field(cls, field_name: str) -> bool:
        """
        判断字段是否需要脱敏
        
        Args:
            field_name: 字段名
            
        Returns:
            是否需要脱敏
        """
        field_lower = field_name.lower()
        return any(
            sensitive in field_lower 
            for sensitive in cls.SENSITIVE_FIELDS
        )
    
    @classmethod
    def mask_value(cls, value: str, field_name: str) -> str:
        """
        对敏感数据进行脱敏
        
        Args:
            value: 原始值
            field_name: 字段名
            
        Returns:
            脱敏后的值
        """
        if value is None:
            return None
        
        if not cls.should_mask_field(field_name):
            return str(value)
        
        value_str = str(value)
        
        # 邮箱脱敏
        if 'email' in field_name.lower() and '@' in value_str:
            parts = value_str.split('@')
            username = parts[0]
            domain = parts[1]
            if len(username) > 2:
                username = username[0] + '*' * (len(username) - 2) + username[-1]
            return f"{username}@{domain}"
        
        # 手机号脱敏
        if any(k in field_name.lower() for k in ['phone', 'mobile', 'tel']):
            if len(value_str) >= 7:
                return value_str[:3] + '*' * 4 + value_str[-4:]
            return '*' * 7
        
        # 密码/密钥类完全隐藏
        if any(k in field_name.lower() for k in ['password', 'secret', 'key', 'token']):
            return '***'
        
        # 其他敏感数据部分隐藏
        if len(value_str) > 4:
            return value_str[:2] + '*' * (len(value_str) - 4) + value_str[-2:]
        
        return '*' * len(value_str)
    
    @classmethod
    def mask_result(cls, columns: List[str], row: dict) -> dict:
        """
        对查询结果进行脱敏处理
        
        Args:
            columns: 列名列表
            row: 查询结果行
            
        Returns:
            脱敏后的结果
        """
        masked_row = {}
        for col in columns:
            value = row.get(col)
            if cls.should_mask_field(col):
                masked_row[col] = cls.mask_value(value, col)
            else:
                masked_row[col] = value
        return masked_row
