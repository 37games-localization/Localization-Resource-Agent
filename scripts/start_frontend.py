#!/usr/bin/env python3
"""Start the local Resource Agent workbench frontend.

VM usage: ask the Agent "打开资源管理工作台" or run this script directly.
The frontend is the same UI for dry-run, TEST_MODE and production; the backend
execution mode is selected inside the page and shown in the event stream.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DEFAULT_PORT = int(os.environ.get("LOC_AGENT_FRONTEND_PORT", "3000"))


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def find_port(start: int) -> int:
    for port in range(start, start + 20):
        if not port_open(port):
            return port
    raise RuntimeError(f"未找到可用端口：{start}-{start + 19}")


def main() -> int:
    if not FRONTEND.exists():
        print(f"❌ 未找到前端目录：{FRONTEND}")
        return 1
    if not shutil.which("npm"):
        print("❌ 未找到 npm。请先安装 Node.js，再重新启动工作台。")
        return 1

    port = find_port(DEFAULT_PORT)
    node_modules = FRONTEND / "node_modules"
    if not node_modules.exists():
        print("首次启动需要安装前端依赖，正在执行 npm install...")
        install = subprocess.run(["npm", "install"], cwd=FRONTEND)
        if install.returncode != 0:
            print("❌ 前端依赖安装失败，请检查网络或 npm 配置。")
            return install.returncode

    env = os.environ.copy()
    env.setdefault("LOC_AGENT_SKILL_ROOT", str(ROOT))
    env.setdefault("PORT", str(port))

    print("启动资源管理 Agent 工作台...")
    print(f"访问地址：http://127.0.0.1:{port}/agent-visual")
    print("说明：同一个前端支持 dry-run / TEST_MODE / production；页面会显示真实执行模式和写回边界。")
    print("按 Ctrl+C 可关闭前端。")

    try:
        if os.environ.get("LOC_AGENT_FRONTEND_OPEN", "1") != "0":
            time.sleep(0.2)
            webbrowser.open(f"http://127.0.0.1:{port}/agent-visual")
        return subprocess.call(["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(port)], cwd=FRONTEND, env=env)
    except KeyboardInterrupt:
        print("\n已关闭资源管理 Agent 工作台。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
