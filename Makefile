.PHONY: install backend frontend seed-maintenance check-maintenance

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

# 阶段一：生成定期检修种子（可重复执行，重复计划编码自动跳过）
seed-maintenance:
	cd backend && .venv/bin/python scripts/generate_maintenance_seed.py

# 阶段二：运行检查（确认依赖与进程，只读探针核对应用、数据库、脚本同源）
check-maintenance:
	cd backend && .venv/bin/python scripts/check_maintenance_runtime.py
