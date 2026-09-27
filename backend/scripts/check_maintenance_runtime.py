"""定期检修运行检查阶段：确认依赖、进程与数据一致性，全程只读，可独立重跑。

检查顺序：
1. 服务依赖：fastapi / uvicorn / pydantic 可导入，应用模块可加载；
2. 本地进程：后端端口是否有服务监听，/api/health 是否返回本应用；
3. 只读探针：GET /api/maintenance 拉取检修计划，与种子文件
   data/maintenance_seed.json 逐条比对，确认应用、数据库（内存仓库）
   与脚本使用的是同一份数据。

探针只发 GET 请求，不改动任何数据；任一步失败以非零码退出。
种子生成阶段见 scripts/generate_maintenance_seed.py。
"""
from __future__ import annotations

import importlib
import json
import socket
import sys
import urllib.request
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SEED_FILE = BACKEND_DIR / "data" / "maintenance_seed.json"
COMPARE_FIELDS = ["设备名称", "检修级别", "计划日期"]
HOST = "127.0.0.1"
FALLBACK_PORT = 8000

failures: list[str] = []


def report(ok: bool, label: str, detail: str = "") -> bool:
    suffix = f" — {detail}" if detail else ""
    print(f"{'✓' if ok else '✗'} {label}{suffix}")
    if not ok:
        failures.append(label)
    return ok


def http_get(url: str) -> dict[str, Any]:
    """只读 GET 探针：拉取 JSON，失败时抛出带说明的异常。"""
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def service_address() -> tuple[str, int]:
    """端口以应用配置为准；配置加载失败时退回默认端口。"""
    try:
        from app.config import settings
        return HOST, settings.port
    except Exception:
        return HOST, FALLBACK_PORT


def check_dependencies() -> None:
    for package in ("fastapi", "uvicorn", "pydantic"):
        try:
            module = importlib.import_module(package)
            report(True, f"依赖 {package}", getattr(module, "__version__", "未知版本"))
        except ImportError as exc:
            report(False, f"依赖 {package}", str(exc))
    for name in ("app.config", "app.store", "app.services.maintenance"):
        try:
            importlib.import_module(name)
            report(True, f"应用模块 {name}")
        except Exception as exc:  # 依赖缺失等原因都会在这里暴露
            report(False, f"应用模块 {name}", str(exc))


def check_process(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            report(True, f"本地进程监听 {host}:{port}")
    except OSError as exc:
        report(False, f"本地进程监听 {host}:{port}", f"{exc}；请先启动后端（make backend）")
        return False
    try:
        payload = http_get(f"http://{host}:{port}/api/health")
    except Exception as exc:
        report(False, "健康检查 /api/health", f"{exc}；端口可能被其他进程占用")
        return False
    try:
        from app.config import settings
        expected_app: str | None = settings.app_name
    except Exception:
        expected_app = None
    ok = payload.get("ok") is True and (expected_app is None or payload.get("app") == expected_app)
    return report(ok, "健康检查 /api/health", json.dumps(payload, ensure_ascii=False))


def fetch_all_plans(host: str, port: int) -> list[dict[str, Any]]:
    """分页拉全检修计划；只发 GET，属于纯只读探针。"""
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = http_get(f"http://{host}:{port}/api/maintenance?page={page}&size=200")
        batch = payload.get("items", [])
        items.extend(batch)
        if not batch or len(items) >= int(payload.get("total", len(items))):
            return items
        page += 1


def check_probe(host: str, port: int) -> None:
    if not SEED_FILE.exists():
        report(False, "种子文件", f"{SEED_FILE} 不存在，请先运行 make seed-maintenance")
        return
    expected_rows = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    try:
        actual_rows = fetch_all_plans(host, port)
    except Exception as exc:
        report(False, "只读探针 GET /api/maintenance", str(exc))
        return
    expected = {str(row.get("计划编号")): row for row in expected_rows}
    actual = {str(row.get("计划编号")): row for row in actual_rows}
    problems = [f"应用缺少 {code}" for code in sorted(expected) if code not in actual]
    problems += [f"应用多出 {code}" for code in sorted(actual) if code not in expected]
    for code in sorted(expected.keys() & actual.keys()):
        for field in COMPARE_FIELDS:
            if str(expected[code].get(field, "")) != str(actual[code].get(field, "")):
                problems.append(
                    f"{code} 的{field}不一致：种子={expected[code].get(field)!r}，应用={actual[code].get(field)!r}"
                )
    if problems:
        hint = "；若刚重新生成种子，请重启后端后重跑本检查"
        report(False, "只读探针 GET /api/maintenance", "；".join(problems) + hint)
        return
    report(True, "只读探针 GET /api/maintenance", f"{len(actual)} 条检修计划与种子文件一致")


def main() -> int:
    host, port = service_address()
    print("阶段一：服务依赖")
    check_dependencies()
    print("阶段二：本地进程状态")
    listening = check_process(host, port)
    print("阶段三：只读探针")
    if listening:
        check_probe(host, port)
    else:
        report(False, "只读探针 GET /api/maintenance", "服务未监听，跳过")
    if failures:
        print(f"\n检查未通过：{len(failures)} 项未达标")
        return 1
    print("\n检查通过：应用、数据库与脚本使用同一份定期检修数据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
