# 工程影像管理平台 - Vercel 在线授权门户

为「工程影像管理平台」本地软件提供**在线注册、机器绑定、授权码生成**服务。

## 核心原则

| 原则 | 实现 |
|------|------|
| ✅ 本地存储 | 工程影像数据仍在用户本地服务器运行 |
| ✅ 网上注册 | 用户在本网站注册账号 |
| ✅ 授权 | 在线生成与本地 `licensing.py` 完全兼容的授权码 |
| ✅ 存储账号 | 用户、机器、授权记录存储于 Vercel Postgres |

## 部署流程（GitHub → Vercel）

### 第一步：推送到 GitHub

```bash
cd vercel_portal

# 在 https://github.com/new 创建一个新仓库（不要勾选任何初始化选项）
# 然后把你的仓库地址替换下面的 URL

git remote add origin https://github.com/你的用户名/album-auth-portal.git
git push -u origin main
```

### 第二步：导入 Vercel

1. 打开 https://vercel.com/new
2. 选择 **Import Git Repository** → 选择刚推送的 GitHub 仓库
3. **Root Directory** 保持默认（仓库根目录就是 portal 代码）
4. Framework Preset → 选 **Other**
5. **Environment Variables** 添加：

| 变量名 | 说明 |
|--------|------|
| `POSTGRES_URL` | Vercel Postgres 连接串（先创建数据库再获取） |
| `FLASK_SECRET_KEY` | 会话密钥（任意长随机字符串，例如 `python -c "import secrets; print(secrets.token_hex(32))"`） |

### 第三步：创建 Vercel Postgres 数据库

在 Vercel Dashboard 中：
1. 进入项目 → **Storage** → **Create Database**
2. 选择 **Postgres** (Neon)
3. 选择 **Hobby** 计划（免费）
4. 创建完成后，环境变量 `POSTGRES_URL` 会自动注入

### 第四步：绑定域名（可选）

```bash
# 安装 Vercel CLI 后
vercel domains add <你的域名.com>
```

或在 Vercel Dashboard → 项目 → **Domains** 中添加。

## 本地软件联动

部署完成后，把 `templates/license.html` 中的在线门户 URL 改为你的 Vercel 域名：

```
{{ online_portal_url or 'https://你的域名.vercel.app' }}
```

## 工作流程

```
┌─ 本地电脑 ─────────────────────┐     ┌─ Vercel 云端 ─────────────────┐
│                                 │     │                                │
│  1. 打开本地软件授权页           │     │  4. 注册/登录账号              │
│  2. 复制「本机机器 ID」         │────▶│  5. 粘贴机器 ID → 获取授权码  │
│  3. 点击「在线获取授权」        │     │  6. 生成授权码                 │
│                                 │     │                                │
│  7. 粘贴授权码 → 激活成功 ✅    │◀────│  授权码已生成                  │
│                                 │     │                                │
└─────────────────────────────────┘     └────────────────────────────────┘
```

## 本地测试

```bash
cd vercel_portal

# 安装依赖
pip install -r requirements.txt

# 需要设置 POSTGRES_URL 环境变量
# 或使用 SQLite 替代（需要修改 db.py）

export FLASK_APP=api/index.py
export FLASK_DEBUG=1
flask run --port 5088
```
