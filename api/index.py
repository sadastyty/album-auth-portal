"""工程影像管理平台 - 在线授权门户 (Vercel Serverless)"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps

import base64
import hashlib
import hmac
import uuid

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_cors import CORS
from werkzeug.security import check_password_hash

# ── 初始化 ──────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())
CORS(app, supports_credentials=True)

# ── 授权常量（与本地软件 licensing.py 保持一致） ────────────────────────
APP_CODE = "HDYX"
LICENSE_SECRET = b"HDYX-LAN-ALBUM-LICENSE-2026-WANGFENG"
LICENSE_TYPE_TERM = "term"
LICENSE_TYPE_LIFETIME = "lifetime"
DEFAULT_LICENSE_VALID_DAYS = 90
LIFETIME_LICENSE_PRICE = 129
TRIAL_VALID_DAYS = 30


# ── 授权码生成（与本地 licensing.py 算法一致） ──────────────────────────
def _canonical_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_payload(payload):
    return hmac.new(LICENSE_SECRET, _canonical_json(payload), hashlib.sha256).hexdigest().upper()


def generate_license_code(machine_id, owner, license_type=LICENSE_TYPE_TERM, valid_days=DEFAULT_LICENSE_VALID_DAYS):
    """生成授权码（与本地 licensing.py 完全相同）"""
    issued_at = datetime.now(timezone.utc)
    license_type = (license_type or LICENSE_TYPE_TERM).lower()
    if license_type == LICENSE_TYPE_LIFETIME:
        valid_days = 0

    payload = {
        "app": APP_CODE,
        "machine_id": machine_id.upper(),
        "owner": owner,
        "issued_at": issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "license_type": license_type,
        "valid_days": 0 if license_type == LICENSE_TYPE_LIFETIME else valid_days,
        "version": 2,
    }
    if license_type == LICENSE_TYPE_LIFETIME:
        payload["lifetime_price"] = LIFETIME_LICENSE_PRICE
    else:
        expires_at = issued_at + timedelta(days=valid_days)
        payload["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    signed = {
        "payload": payload,
        "signature": _sign_payload(payload),
    }
    raw = json.dumps(signed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_license_code(code):
    """解码并验证授权码"""
    code = code.strip()
    padded = code + "=" * (-len(code) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("授权码格式无效") from exc
    payload = data.get("payload") or {}
    signature = str(data.get("signature", "")).upper()
    if not payload or not signature:
        raise ValueError("授权码内容不完整")
    expected = _sign_payload(payload)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("授权码签名无效")
    if payload.get("app") != APP_CODE:
        raise ValueError("授权码不适用于本软件")
    return payload


# ── 数据库初始化 ────────────────────────────────────────────────────────
from .db import (  # noqa: E402
    create_user, get_user_by_username, get_user_by_id,
    register_machine, get_user_machines, get_machine_by_id,
    save_license, get_user_licenses, get_license_by_code,
    get_all_licenses, get_all_users, get_all_machines,
    update_user_role, init_db,
)


def ensure_db():
    """确保数据库已初始化（首次请求时）"""
    if not hasattr(app, "_db_initialized"):
        try:
            init_db()
            app._db_initialized = True
        except Exception as e:
            print(f"[DB Init Warning] {e}")
            app._db_initialized = False


# ── 装饰器 ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "error": "请先登录"}), 401
        user = get_user_by_id(user_id)
        if not user:
            session.clear()
            return jsonify({"ok": False, "error": "用户不存在"}), 401
        return f(user, *args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "error": "请先登录"}), 401
        user = get_user_by_id(user_id)
        if not user or user["role"] != "admin":
            return jsonify({"ok": False, "error": "需要管理员权限"}), 403
        return f(user, *args, **kwargs)
    return decorated


# ── 首页路由 ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/register")
def register_page():
    return render_template("register.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


# ── 认证 API ────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    """健康检查 + 登录状态"""
    ensure_db()
    user = None
    if session.get("user_id"):
        u = get_user_by_id(session["user_id"])
        if u:
            user = {
                "id": u["id"],
                "username": u["username"],
                "display_name": u["display_name"],
                "email": u["email"],
                "company": u["company"],
                "role": u["role"],
            }
    return jsonify({
        "ok": True,
        "logged_in": user is not None,
        "user": user,
    })


@app.route("/api/register", methods=["POST"])
def api_register():
    """用户注册"""
    ensure_db()
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    confirm = str(data.get("confirm_password", "")).strip()
    email = str(data.get("email", "")).strip()
    display_name = str(data.get("display_name", "")).strip()
    company = str(data.get("company", "")).strip()
    phone = str(data.get("phone", "")).strip()

    if not username or len(username) < 2:
        return jsonify({"ok": False, "error": "用户名至少 2 个字符"}), 400
    if not re.match(r"^[\u4e00-\u9fa5a-zA-Z0-9_]{2,20}$", username):
        return jsonify({"ok": False, "error": "用户名限 2-20 位中文/字母/数字/下划线"}), 400
    if not password or len(password) < 6:
        return jsonify({"ok": False, "error": "密码至少 6 个字符"}), 400
    if password != confirm:
        return jsonify({"ok": False, "error": "两次密码输入不一致"}), 400
    if get_user_by_username(username):
        return jsonify({"ok": False, "error": "用户名已被注册"}), 409

    try:
        user = create_user(username, password, email, display_name, company, phone)
        if not user:
            return jsonify({"ok": False, "error": "注册失败"}), 500
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        return jsonify({
            "ok": True,
            "message": "注册成功",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"注册失败：{str(e)}"}), 500


@app.route("/api/login", methods=["POST"])
def api_login():
    """用户登录"""
    ensure_db()
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not username or not password:
        return jsonify({"ok": False, "error": "请输入用户名和密码"}), 400

    user = get_user_by_username(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"ok": False, "error": "用户名或密码错误"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]

    return jsonify({
        "ok": True,
        "message": "登录成功",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "company": user["company"],
            "role": user["role"],
        }
    })


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True, "message": "已退出登录"})


# ── 用户 API ────────────────────────────────────────────────────────────
@app.route("/api/user/profile")
@login_required
def api_user_profile(user):
    return jsonify({
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "company": user["company"],
            "phone": user["phone"],
            "role": user["role"],
            "created_at": user["created_at"].isoformat() if user["created_at"] else "",
        }
    })


@app.route("/api/user/profile", methods=["PUT"])
@login_required
def api_update_profile(user):
    data = request.get_json(silent=True) or {}
    from .db import execute as db_execute
    fields = []
    values = []
    for key in ("display_name", "email", "company", "phone"):
        if key in data:
            fields.append(f"{key} = %s")
            values.append(str(data[key]).strip())
    if fields:
        fields.append("updated_at = (NOW() AT TIME ZONE 'utc')")
        values.append(user["id"])
        db_execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = %s",
            values
        )
    return jsonify({"ok": True, "message": "已更新"})


# ── 机器管理 API ────────────────────────────────────────────────────────
@app.route("/api/machines")
@login_required
def api_list_machines(user):
    machines = get_user_machines(user["id"])
    return jsonify({
        "ok": True,
        "machines": [dict(m) for m in machines],
    })


@app.route("/api/machines/register", methods=["POST"])
@login_required
def api_register_machine(user):
    data = request.get_json(silent=True) or {}
    machine_id = str(data.get("machine_id", "")).strip().upper()
    hostname = str(data.get("hostname", "")).strip()
    description = str(data.get("description", "")).strip()

    if not machine_id:
        return jsonify({"ok": False, "error": "请输入机器 ID"}), 400
    if not re.match(r"^[A-Z0-9\-]{8,50}$", machine_id):
        return jsonify({"ok": False, "error": "机器 ID 格式无效"}), 400

    try:
        machine = register_machine(user["id"], machine_id, hostname, description)
        return jsonify({"ok": True, "message": "机器已注册", "machine": dict(machine)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"注册失败：{str(e)}"}), 500


# ── 授权 API ────────────────────────────────────────────────────────────
@app.route("/api/licenses")
@login_required
def api_list_licenses(user):
    """获取用户的所有授权码"""
    licenses = get_user_licenses(user["id"])
    result = []
    for lic in licenses:
        item = dict(lic)
        for k in ("issued_at", "expires_at", "created_at"):
            if item.get(k) and hasattr(item[k], "isoformat"):
                item[k] = item[k].isoformat()
        result.append(item)
    return jsonify({"ok": True, "licenses": result})


@app.route("/api/licenses/generate", methods=["POST"])
@login_required
def api_generate_license(user):
    """生成授权码"""
    data = request.get_json(silent=True) or {}
    machine_id = str(data.get("machine_id", "")).strip().upper()
    owner = str(data.get("owner", "")).strip() or user["display_name"] or user["username"]
    license_type = str(data.get("license_type", LICENSE_TYPE_TERM)).lower()
    valid_days = int(data.get("valid_days", DEFAULT_LICENSE_VALID_DAYS) or DEFAULT_LICENSE_VALID_DAYS)

    if not machine_id:
        return jsonify({"ok": False, "error": "请指定机器 ID"}), 400

    # 检查是否已为此机器生成过授权
    existing = get_machine_by_id(machine_id)
    if not existing:
        # 自动注册这台机器
        register_machine(user["id"], machine_id)

    # 生成授权码
    try:
        code = generate_license_code(machine_id, owner, license_type, valid_days)
        payload = decode_license_code(code)

        issued_at = datetime.strptime(
            payload["issued_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)

        expires_at = None
        is_lifetime = license_type == LICENSE_TYPE_LIFETIME
        if not is_lifetime and payload.get("expires_at"):
            expires_at = datetime.strptime(
                payload["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)

        # 保存到数据库
        saved = save_license(
            user_id=user["id"],
            machine_id=machine_id,
            owner=owner,
            license_code=code,
            license_type=license_type,
            issued_at=issued_at,
            expires_at=expires_at,
            is_lifetime=is_lifetime,
        )

        return jsonify({
            "ok": True,
            "message": "授权码已生成",
            "license": {
                "id": saved["id"],
                "license_code": code,
                "machine_id": machine_id,
                "owner": owner,
                "license_type": license_type,
                "issued_at": payload["issued_at"],
                "expires_at": payload.get("expires_at", ""),
                "is_lifetime": is_lifetime,
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"生成失败：{str(e)}"}), 500


@app.route("/api/license/verify", methods=["POST"])
def api_verify_license():
    """验证授权码（供本地软件调用）"""
    data = request.get_json(silent=True) or {}
    license_code = str(data.get("license_code", "")).strip()
    machine_id = str(data.get("machine_id", "")).strip().upper()

    if not license_code:
        return jsonify({"ok": False, "error": "授权码不能为空"}), 400

    try:
        payload = decode_license_code(license_code)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # 验证机器 ID
    if machine_id:
        expected = machine_id.upper()
        actual = str(payload.get("machine_id", "")).upper()
        if actual != expected:
            return jsonify({"ok": False, "error": "授权码与本机机器 ID 不匹配"}), 400

    # 检查数据库记录
    db_lic = get_license_by_code(license_code)
    if db_lic and not db_lic["is_active"]:
        return jsonify({"ok": False, "error": "授权码已被禁用"}), 400

    is_lifetime = payload.get("license_type") == LICENSE_TYPE_LIFETIME
    if not is_lifetime and payload.get("expires_at"):
        expiry = datetime.strptime(
            payload["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expiry:
            return jsonify({"ok": False, "error": "授权码已到期"}), 400

    return jsonify({
        "ok": True,
        "payload": payload,
        "is_lifetime": is_lifetime,
    })


# ── 管理员 API ──────────────────────────────────────────────────────────
@app.route("/api/admin/users")
@admin_required
def api_admin_users(user):
    users = get_all_users()
    return jsonify({
        "ok": True,
        "users": [dict(u) for u in users],
    })


@app.route("/api/admin/licenses")
@admin_required
def api_admin_licenses(user):
    licenses = get_all_licenses()
    result = []
    for lic in licenses:
        item = dict(lic)
        for k in ("issued_at", "expires_at", "created_at"):
            if item.get(k) and hasattr(item[k], "isoformat"):
                item[k] = item[k].isoformat()
        result.append(item)
    return jsonify({"ok": True, "licenses": result})


@app.route("/api/admin/machines")
@admin_required
def api_admin_machines(user):
    machines = get_all_machines()
    return jsonify({
        "ok": True,
        "machines": [dict(m) for m in machines],
    })


@app.route("/api/admin/user/<int:target_id>/role", methods=["PUT"])
@admin_required
def api_admin_set_role(user, target_id):
    data = request.get_json(silent=True) or {}
    role = str(data.get("role", "")).strip()
    if role not in ("user", "admin"):
        return jsonify({"ok": False, "error": "角色无效"}), 400
    update_user_role(target_id, role)
    return jsonify({"ok": True, "message": "角色已更新"})


# ── 在线激活页面 API ─────────────────────────────────────────────────────
@app.route("/api/activate", methods=["POST"])
def api_online_activate():
    """在线激活：用户提交机器 ID，系统自动生成授权码"""
    ensure_db()
    data = request.get_json(silent=True) or {}
    machine_id = str(data.get("machine_id", "")).strip().upper()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not machine_id:
        return jsonify({"ok": False, "error": "请输入机器 ID"}), 400
    if not username or not password:
        return jsonify({"ok": False, "error": "请输入账号密码"}), 400

    user = get_user_by_username(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"ok": False, "error": "账号或密码错误"}), 401

    # 检查是否已有授权
    existing = get_machine_by_id(machine_id)
    if existing and existing["user_id"] != user["id"]:
        return jsonify({"ok": False, "error": "此机器 ID 已绑定其他账号"}), 409

    # 注册机器
    register_machine(user["id"], machine_id)

    # 检查是否已有授权码
    user_licenses = get_user_licenses(user["id"])
    for lic in user_licenses:
        if lic["machine_id"] == machine_id and lic["is_active"]:
            return jsonify({
                "ok": True,
                "message": "此机器已有有效授权",
                "license_code": lic["license_code"],
                "is_lifetime": lic["is_lifetime"],
                "expires_at": lic["expires_at"].isoformat() if lic["expires_at"] else "",
            })

    # 生成试用授权（30天）
    owner = user["display_name"] or user["username"]
    try:
        code = generate_license_code(machine_id, owner, LICENSE_TYPE_TERM, TRIAL_VALID_DAYS)
        payload = decode_license_code(code)
        issued_at = datetime.strptime(
            payload["issued_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        expires_at = issued_at + timedelta(days=TRIAL_VALID_DAYS)

        save_license(
            user_id=user["id"],
            machine_id=machine_id,
            owner=owner,
            license_code=code,
            license_type=LICENSE_TYPE_TERM,
            issued_at=issued_at,
            expires_at=expires_at,
            is_lifetime=False,
        )

        return jsonify({
            "ok": True,
            "message": f"授权成功，有效期 {TRIAL_VALID_DAYS} 天",
            "license_code": code,
            "is_lifetime": False,
            "expires_at": expires_at.isoformat(),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"授权失败：{str(e)}"}), 500


