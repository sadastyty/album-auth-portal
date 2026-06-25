"""工程影像管理平台 - Vercel 在线授权门户

部署流程:
  1. 安装 Vercel CLI: npm install -g vercel
  2. 登录 Vercel: vercel login
  3. 创建 Postgres 数据库: vercel add postgres  或 在 Vercel Dashboard 创建
  4. 设置环境变量:
     - POSTGRES_URL: Vercel Postgres 连接串 (自动注入)
     - FLASK_SECRET_KEY: 会话密钥 (任意长随机字符串)
  5. 部署: vercel --prod
  6. 绑定域名: vercel domains add <your-domain.com>

原理说明:
  - 本地存储: 工程影像数据仍在用户本地局域网服务器
  - 网上注册: 用户在 Vercel 网站注册账号
  - 授权: 在线生成与本地 licensing.py 兼容的授权码
  - 存储账号: 用户账号、机器ID、授权记录存储于 Vercel Postgres
"""
