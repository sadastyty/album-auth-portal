"""Vercel Postgres 数据库连接和模型定义"""

import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

# 从 Vercel 环境变量读取 Postgres 连接串
DATABASE_URL = os.environ.get("POSTGRES_URL", os.environ.get("DATABASE_URL", ""))


def get_conn():
    """获取数据库连接"""
    if not DATABASE_URL:
        raise RuntimeError("未配置 POSTGRES_URL 环境变量")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """初始化数据库表结构（幂等）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    email VARCHAR(200) DEFAULT '',
                    role VARCHAR(20) DEFAULT 'user',
                    display_name VARCHAR(100) DEFAULT '',
                    company VARCHAR(200) DEFAULT '',
                    phone VARCHAR(30) DEFAULT '',
                    created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
                    updated_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS machines (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    machine_id VARCHAR(100) NOT NULL,
                    hostname VARCHAR(200) DEFAULT '',
                    description VARCHAR(500) DEFAULT '',
                    created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
                    UNIQUE(machine_id)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS licenses (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    machine_id VARCHAR(100) NOT NULL,
                    owner VARCHAR(100) NOT NULL,
                    license_code TEXT NOT NULL,
                    license_type VARCHAR(20) DEFAULT 'term',
                    issued_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
                    expires_at TIMESTAMP,
                    is_lifetime BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc')
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS license_orders (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    order_no VARCHAR(50) UNIQUE NOT NULL,
                    amount NUMERIC(10,2) DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'pending',
                    payment_method VARCHAR(50) DEFAULT '',
                    remark TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
                    paid_at TIMESTAMP
                );
            """)
        conn.commit()
    finally:
        conn.close()


def query_one(sql, params=None):
    """查询单行"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        conn.close()


def query_all(sql, params=None):
    """查询多行"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def execute(sql, params=None):
    """执行写操作，返回影响行数"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def create_user(username, password, email="", display_name="", company="", phone=""):
    """创建新用户"""
    pw_hash = generate_password_hash(password)
    sql = """
        INSERT INTO users (username, password_hash, email, display_name, company, phone, role)
        VALUES (%s, %s, %s, %s, %s, %s, 'user')
        RETURNING id, username, role, created_at
    """
    return query_one(sql, (username, pw_hash, email, display_name, company, phone))


def get_user_by_username(username):
    """通过用户名查找用户"""
    return query_one("SELECT * FROM users WHERE username = %s", (username,))


def get_user_by_id(user_id):
    """通过ID查找用户"""
    return query_one("SELECT * FROM users WHERE id = %s", (user_id,))


def register_machine(user_id, machine_id, hostname="", description=""):
    """注册机器ID"""
    sql = """
        INSERT INTO machines (user_id, machine_id, hostname, description)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (machine_id) DO UPDATE
        SET user_id = EXCLUDED.user_id,
            hostname = EXCLUDED.hostname,
            description = EXCLUDED.description
        RETURNING id, machine_id, created_at
    """
    return query_one(sql, (user_id, machine_id, hostname, description))


def get_user_machines(user_id):
    """获取用户的所有机器"""
    return query_all(
        "SELECT * FROM machines WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )


def get_machine_by_id(machine_id):
    """通过机器ID查找"""
    return query_one("SELECT * FROM machines WHERE machine_id = %s", (machine_id,))


def save_license(user_id, machine_id, owner, license_code, license_type,
                 issued_at, expires_at, is_lifetime):
    """保存授权码"""
    sql = """
        INSERT INTO licenses (user_id, machine_id, owner, license_code,
                              license_type, issued_at, expires_at, is_lifetime, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        RETURNING id, license_code, created_at
    """
    return query_one(sql, (
        user_id, machine_id, owner, license_code,
        license_type, issued_at, expires_at, is_lifetime
    ))


def get_user_licenses(user_id):
    """获取用户的所有授权"""
    return query_all(
        """SELECT l.*, m.hostname
           FROM licenses l
           LEFT JOIN machines m ON l.machine_id = m.machine_id
           WHERE l.user_id = %s
           ORDER BY l.created_at DESC""",
        (user_id,)
    )


def get_all_licenses():
    """获取所有授权（管理员用）"""
    return query_all(
        """SELECT l.*, u.username, u.display_name
           FROM licenses l
           JOIN users u ON l.user_id = u.id
           ORDER BY l.created_at DESC"""
    )


def get_all_users():
    """获取所有用户（管理员用）"""
    return query_all(
        "SELECT id, username, email, display_name, company, role, created_at FROM users ORDER BY created_at DESC"
    )


def get_all_machines():
    """获取所有机器（管理员用）"""
    return query_all(
        """SELECT m.*, u.username
           FROM machines m
           JOIN users u ON m.user_id = u.id
           ORDER BY m.created_at DESC"""
    )


def update_user_role(user_id, role):
    """更新用户角色"""
    return execute(
        "UPDATE users SET role = %s, updated_at = (NOW() AT TIME ZONE 'utc') WHERE id = %s",
        (role, user_id)
    )


def get_license_by_code(license_code):
    """通过授权码查找"""
    return query_one(
        "SELECT * FROM licenses WHERE license_code = %s",
        (license_code,)
    )
