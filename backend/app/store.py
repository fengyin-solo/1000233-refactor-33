"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.seed import SEED_ROWS

# 生成阶段（backend/scripts/generate_maintenance_seed.py）的产出，启动时合并进定期检修表
GENERATED_SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "maintenance.generated.json"


def load_generated_rows() -> list[dict[str, Any]]:
    """读取生成阶段产出的定期检修种子；文件不存在时返回空列表。"""
    if not GENERATED_SEED_FILE.exists():
        return []
    try:
        data = json.loads(GENERATED_SEED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"生成的种子文件 {GENERATED_SEED_FILE} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"生成的种子文件 {GENERATED_SEED_FILE} 应为记录列表")
    return [row for row in data if isinstance(row, dict)]


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._merge_generated()

    def _merge_generated(self) -> None:
        """合并生成阶段的定期检修种子；计划编号重复的直接跳过，保证幂等。"""
        generated = load_generated_rows()
        if not generated:
            return
        table = self._tables.setdefault("maintenance", [])
        existing = {str(row.get("计划编号", "")) for row in table}
        for row in generated:
            code = str(row.get("计划编号", ""))
            if not code or code in existing:
                continue
            table.append(dict(row))
            existing.add(code)

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
