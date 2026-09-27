"""定期检修种子生成阶段：只读取设备名称、检修级别、计划日期，重复计划编码直接跳过。

输入：data/maintenance_plan_input.csv（只需 设备名称,检修级别,计划日期 三列，其余列忽略）
输出：data/maintenance_seed.json（后端启动时加载的同一份数据）

计划编码按输入行位置确定性生成（MAIN-0001、MAIN-0002……）：
- 编码已存在于种子文件时直接跳过该行，不报错、不覆盖；
- 因此本阶段可独立反复执行，重跑不会产生重复数据；
- 为保证编码稳定，输入文件请只追加新行，不要删改历史行。

运行检查阶段见 scripts/check_maintenance_runtime.py。
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = BACKEND_DIR / "data" / "maintenance_plan_input.csv"
SEED_FILE = BACKEND_DIR / "data" / "maintenance_seed.json"

REQUIRED_COLUMNS = ["设备名称", "检修级别", "计划日期"]
CODE_PREFIX = "MAIN"
DEFAULT_STATUS = "待批准"


def read_input_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    """只读取设备名称、检修级别、计划日期三列；返回 (输入行位置, 行数据)。"""
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [col for col in REQUIRED_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"✗ 输入文件缺少必需列：{'、'.join(missing)}（{path}）")
        rows: list[tuple[int, dict[str, str]]] = []
        for raw in reader:
            row = {col: (raw.get(col) or "").strip() for col in REQUIRED_COLUMNS}
            if not any(row.values()):
                continue
            rows.append((len(rows) + 1, row))
        return rows


def validate(row: dict[str, str]) -> str | None:
    """校验三列内容；返回 None 表示通过，否则返回可读的跳过原因。"""
    empty = [col for col in REQUIRED_COLUMNS if not row[col]]
    if empty:
        return f"必填列未填写：{'、'.join(empty)}"
    try:
        datetime.strptime(row["计划日期"], "%Y-%m-%d")
    except ValueError:
        return f"计划日期应为 YYYY-MM-DD，实际为 {row['计划日期']!r}"
    return None


def build_entry(position: int, row: dict[str, str]) -> dict[str, Any]:
    """由三列生成一条完整检修计划，其余字段给默认值。"""
    return {
        "id": position,
        "计划编号": f"{CODE_PREFIX}-{position:04d}",
        "设备名称": row["设备名称"],
        "检修级别": row["检修级别"],
        "计划日期": row["计划日期"],
        "检修班组": "",
        "检修时长": "",
        "验收结果": "",
        "计划状态": DEFAULT_STATUS,
        "status": DEFAULT_STATUS,
        "pending": True,
        "abnormal": False,
    }


def write_seed(path: Path, rows: list[dict[str, Any]]) -> None:
    """原子写入，避免写一半损坏共享种子文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
    ) as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    Path(fh.name).replace(path)


def main() -> int:
    if not INPUT_FILE.exists():
        print(f"✗ 找不到输入文件 {INPUT_FILE}")
        return 1
    input_rows = read_input_rows(INPUT_FILE)
    existing: list[dict[str, Any]] = []
    if SEED_FILE.exists():
        existing = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    known_codes = {str(row.get("计划编号", "")) for row in existing}

    created: list[str] = []
    skipped: list[str] = []
    invalid = 0
    for position, row in input_rows:
        problem = validate(row)
        if problem:
            print(f"! 第 {position} 行跳过：{problem}")
            invalid += 1
            continue
        entry = build_entry(position, row)
        code = str(entry["计划编号"])
        if code in known_codes:
            skipped.append(code)
            continue
        existing.append(entry)
        known_codes.add(code)
        created.append(code)

    write_seed(SEED_FILE, existing)

    print(f"输入 {len(input_rows)} 行：新增 {len(created)} 条，重复编码跳过 {len(skipped)} 条，无效行 {invalid} 条")
    if created:
        print(f"  新增：{'、'.join(created)}")
    if skipped:
        print(f"  跳过：{'、'.join(skipped)}")
    print(f"种子文件：{SEED_FILE}（共 {len(existing)} 条）")
    print("提示：后端已在运行时需重启才会加载新种子，随后可运行 make check-maintenance 核对。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
