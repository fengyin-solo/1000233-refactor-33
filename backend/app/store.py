"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
定期检修模块优先读取 scripts 生成的 data/maintenance_seed.json，
保证应用、检查脚本与种子文件用的是同一份数据；文件缺失时回退到内置示例。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.seed import SEED_ROWS

MAINTENANCE_SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "maintenance_seed.json"


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._load_maintenance_seed()

    def _load_maintenance_seed(self) -> None:
        """定期检修以生成的种子文件为准；文件缺失或损坏时回退到内置示例数据。"""
        if not MAINTENANCE_SEED_FILE.exists():
            return
        try:
            rows = json.loads(MAINTENANCE_SEED_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(rows, list):
            self._tables["maintenance"] = [dict(row) for row in rows]

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
