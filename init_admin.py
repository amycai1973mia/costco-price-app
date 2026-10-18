#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建运营者(admin)账号: 交互输入，不把明文密码写进代码/仓库。
用法: .venv/bin/python init_admin.py   然后按提示输入邮箱和密码。"""
import getpass, sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash
import app_main
app_main.init_db()
email = input("运营者邮箱: ").strip().lower()
pw = getpass.getpass("设置密码(至少6位): ")
if len(pw) < 6: raise SystemExit("密码太短，已取消。")
con = sqlite3.connect(Path(__file__).parent / "data" / "costco_app.db")
try:
    con.execute("INSERT INTO users(email,password_hash,role,display_name) VALUES(?,?, 'admin','运营者')", (email, generate_password_hash(pw)))
    con.commit(); print("管理员创建成功:", email)
except sqlite3.IntegrityError:
    con.execute("UPDATE users SET password_hash=?, role='admin' WHERE email=?", (generate_password_hash(pw), email)); con.commit(); print("该邮箱已存在，已提升为管理员并重置密码:", email)
con.close()
