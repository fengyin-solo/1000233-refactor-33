#!/usr/bin/env python3
"""定期检修种子 · 生成阶段（可独立重跑）。

只读取输入 CSV 里的 设备名称 / 检修级别 / 计划日期 三列（其余列忽略），
计划编号由这三个字段确定性生成；已存在的计划编号直接跳过，
所以重复执行不会产生重复数据，也不依赖服务是否在运行。

用法：
    python3 scripts/generate_maintenance_seed.py   # 在 backend/ 下
    make seed-maintenance                          # 或在仓库根目录
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.seed import SEED_ROWS  # noqa: E402

MODULE = "maintenance"
INPUT_FILE = BACKEND_DIR / "data" / "maintenance_plan_input.csv"
OUTPUT_FILE = BACKEND_DIR / "data" / "maintenance.generated.json"

# 生成阶段只读取这三列，其余字段一律给默认值
REQUIRED_COLUMNS = ["设备名称", "检修级别", "计划日期"]
DEFAULT_VALUES = {
    "检修班组": "待分配",
    "检修时长": "待定",
    "验收结果": "未验收",
    "计划状态": "待批准",
}
INITIAL_STATUS = "待批准"  # 与 app/services/maintenance.py 的 STATUS_ORDER[0] 保持一致


def plan_code(equipment: str, level: str, plan_date: str) -> str:
    """由三个输入字段确定性生成计划编号：同样的输入永远得到同样的编号。"""
    digest = hashlib.sha1(f"{equipment}|{level}|{plan_date}".encode("utf-8")).hexdigest()
    return f"MAIN-{digest[:8].upper()}"


def load_generated_rows() -> list[dict[str, Any]]:
    if not OUTPUT_FILE.exists():
        return []
    data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{OUTPUT_FILE} 应为记录列表，请先修正或删除该文件")
    return [row for row in data if isinstance(row, dict)]


def read_input_rows() -> list[dict[str, str]]:
    with INPUT_FILE.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [col for col in REQUIRED_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{INPUT_FILE} 缺少必需列：{'、'.join(missing)}")
        return [{col: (row.get(col) or "").strip() for col in REQUIRED_COLUMNS} for row in reader]


def build_row(entry_id: int, values: dict[str, str]) -> dict[str, Any]:
    code = plan_code(values["设备名称"], values["检修级别"], values["计划日期"])
    return {
        "id": entry_id,
        "status": INITIAL_STATUS,
        "pending": True,
        "abnormal": False,
        "计划编号": code,
        **values,
        **DEFAULT_VALUES,
    }


def write_rows(rows: list[dict[str, Any]]) -> None:
    """先写临时文件再替换，避免写一半被应用进程读到。"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=OUTPUT_FILE.parent, delete=False, suffix=".tmp"
    ) as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        tmp = Path(fh.name)
    tmp.replace(OUTPUT_FILE)


def main() -> int:
    if not INPUT_FILE.exists():
        print(f"✗ 输入文件不存在：{INPUT_FILE}")
        print("  请按「设备名称,检修级别,计划日期」三列准备 CSV 后重跑。")
        return 1

    try:
        inputs = read_input_rows()
        generated = load_generated_rows()
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1

    existing_codes = {str(row.get("计划编号", "")) for row in SEED_ROWS.get(MODULE, [])}
    existing_codes |= {str(row.get("计划编号", "")) for row in generated}
    next_id = max(
        [int(row.get("id", 0)) for row in SEED_ROWS.get(MODULE, [])]
        + [int(row.get("id", 0)) for row in generated]
        + [0]
    ) + 1

    created: list[dict[str, Any]] = []
    skipped = 0
    invalid = 0
    for values in inputs:
        if not all(values[col] for col in REQUIRED_COLUMNS):
            print(f"  跳过无效行（存在空字段）：{values}")
            invalid += 1
            continue
        try:
            date.fromisoformat(values["计划日期"])
        except ValueError:
            print(f"  跳过无效行（计划日期应为 YYYY-MM-DD）：{values}")
            invalid += 1
            continue
        code = plan_code(values["设备名称"], values["检修级别"], values["计划日期"])
        if code in existing_codes:
            skipped += 1
            continue
        created.append(build_row(next_id, values))
        existing_codes.add(code)
        next_id += 1

    if created:
        write_rows(generated + created)

    print(f"✓ 生成阶段完成：新增 {len(created)} 条，跳过重复计划编号 {skipped} 条，无效行 {invalid} 条")
    for row in created:
        print(f"  + {row['计划编号']}  {row['设备名称']} / {row['检修级别']} / {row['计划日期']}")
    print(f"  输出：{OUTPUT_FILE}（共 {len(generated) + len(created)} 条生成记录）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
