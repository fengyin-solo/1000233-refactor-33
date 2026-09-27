#!/usr/bin/env python3
"""定期检修种子 · 检查阶段（只读，可独立重跑）。

依次确认：
1. 服务依赖：fastapi / uvicorn / pydantic 可导入，app 包（配置、种子、仓库）加载正常；
2. 本地进程：后端端口在监听，/api/health 返回正常；
3. 数据一致：用只读探针（GET）调用检修查询接口，比对
   脚本（种子文件）、数据库（内存仓库）、应用（运行中的接口）
   三方是否使用同一份数据。

本阶段只发 GET 请求、只读文件，不改任何数据；任何一步失败以非零码退出。

用法：
    python3 scripts/check_maintenance.py   # 在 backend/ 下
    make check-maintenance                 # 或在仓库根目录
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

MODULE = "maintenance"
GENERATED_FILE = BACKEND_DIR / "data" / "maintenance.generated.json"
REQUIRED_PACKAGES = ["fastapi", "uvicorn", "pydantic"]
PROBE_PAGE_SIZE = 200  # 与路由里每页上限一致

failures: list[str] = []


def ok(message: str) -> None:
    print(f"  ✓ {message}")


def fail(message: str) -> None:
    print(f"  ✗ {message}")
    failures.append(message)


def check_dependencies() -> bool:
    print("[1/4] 服务依赖")
    healthy = True
    for package in REQUIRED_PACKAGES:
        if importlib.util.find_spec(package) is not None:
            ok(f"{package} 可导入（解释器：{sys.executable}）")
        else:
            fail(f"{package} 未安装，请先执行 pip install -r requirements.txt")
            healthy = False
    try:
        from app.config import settings  # noqa: F401
        from app.seed import SEED_ROWS  # noqa: F401
        from app.store import Store  # noqa: F401
    except Exception as exc:  # 依赖或代码损坏时给出可读原因
        fail(f"app 包加载失败：{exc}")
        healthy = False
    else:
        ok("app 包（config / seed / store）加载正常")
    return healthy


def check_process(host: str, port: int) -> bool:
    print("[2/4] 本地进程状态")
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError:
        fail(f"{host}:{port} 未监听，后端进程未在运行（先执行 ./run.sh 或 make backend）")
        return False
    ok(f"{host}:{port} 已监听，后端进程在运行")
    try:
        payload = http_get(f"http://{host}:{port}/api/health")
    except RuntimeError as exc:
        fail(f"健康检查失败：{exc}")
        return False
    if payload.get("ok") is True:
        ok(f"/api/health 正常（应用：{payload.get('app')}，模块数：{payload.get('modules')}）")
        return True
    fail(f"/api/health 返回异常：{payload}")
    return False


def http_get(url: str) -> Any:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {url} 失败：{exc}") from exc


def probe_app_codes(host: str, port: int) -> set[str] | None:
    """只读探针：分页拉取检修列表，返回运行中应用看到的计划编号集合。"""
    codes: set[str] = set()
    page = 1
    while True:
        payload = http_get(f"http://{host}:{port}/api/maintenance?page={page}&size={PROBE_PAGE_SIZE}")
        for item in payload.get("items", []):
            code = str(item.get("计划编号", ""))
            if code:
                codes.add(code)
        if len(codes) >= int(payload.get("total", 0)):
            return codes
        page += 1


def script_view_codes() -> set[str]:
    """脚本视角：内置种子 + 生成阶段产出的文件。"""
    from app.seed import SEED_ROWS

    codes = {str(row.get("计划编号", "")) for row in SEED_ROWS.get(MODULE, [])}
    if GENERATED_FILE.exists():
        data = json.loads(GENERATED_FILE.read_text(encoding="utf-8"))
        codes |= {str(row.get("计划编号", "")) for row in data if isinstance(row, dict)}
    codes.discard("")
    return codes


def database_view_codes() -> set[str]:
    """数据库视角：新建一个内存仓库，按应用启动时同样的规则加载数据。"""
    from app.store import Store

    codes = {str(row.get("计划编号", "")) for row in Store().rows(MODULE)}
    codes.discard("")
    return codes


def check_consistency(host: str, port: int) -> bool:
    print("[3/4] 只读探针：GET /api/maintenance")
    try:
        app_codes = probe_app_codes(host, port)
    except RuntimeError as exc:
        fail(str(exc))
        return False
    assert app_codes is not None
    ok(f"探针读到 {len(app_codes)} 条检修计划")

    print("[4/4] 数据一致性：脚本 / 数据库 / 应用")
    try:
        script_codes = script_view_codes()
        db_codes = database_view_codes()
    except Exception as exc:
        fail(f"读取本地数据失败：{exc}")
        return False

    consistent = True
    for label, left, right in [
        ("脚本 vs 数据库", script_codes, db_codes),
        ("数据库 vs 应用", db_codes, app_codes),
    ]:
        if left == right:
            ok(f"{label}一致（{len(left)} 个计划编号）")
            continue
        fail(f"{label}不一致")
        only_left = sorted(left - right)
        only_right = sorted(right - left)
        if only_left:
            print(f"    仅前者有：{'、'.join(only_left)}")
        if only_right:
            print(f"    仅后者有：{'、'.join(only_right)}")
        consistent = False
    if not consistent and script_codes == db_codes:
        print("    提示：本地数据一致而接口不一致，多半是后端在生成阶段之前启动，重启后端后重跑本检查。")
    return consistent


def main() -> int:
    from app.config import settings

    host, port = "127.0.0.1", settings.port
    print(f"定期检修 · 检查阶段（目标 {host}:{port}，全程只读）")

    deps_ok = check_dependencies()
    process_ok = check_process(host, port)
    if deps_ok and process_ok:
        check_consistency(host, port)
    else:
        print("[3/4]、[4/4] 跳过：前置条件未满足")

    if failures:
        print(f"\n✗ 检查未通过（{len(failures)} 项）：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n✓ 检查通过：依赖、进程正常，应用、数据库和脚本使用同一份数据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
