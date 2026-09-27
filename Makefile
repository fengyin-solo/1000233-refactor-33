.PHONY: install backend frontend seed-maintenance check-maintenance

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

seed-maintenance:
	cd backend && if [ -x .venv/bin/python ]; then .venv/bin/python scripts/generate_maintenance_seed.py; else python3 scripts/generate_maintenance_seed.py; fi

check-maintenance:
	cd backend && if [ -x .venv/bin/python ]; then .venv/bin/python scripts/check_maintenance.py; else python3 scripts/check_maintenance.py; fi
