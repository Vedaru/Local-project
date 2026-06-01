.PHONY: install test lint format clean pre-commit

install:
	python -m pip install -r requirements.txt

test:
	python -m pytest tests/ -v

lint:
	black --check modules/ tests/ main.py application.py microservices/
	isort --check-only modules/ tests/ main.py application.py microservices/
	ruff check modules/ tests/ main.py application.py microservices/
	python -m mypy modules/ microservices/ main.py application.py

format:
	black modules/ tests/ main.py application.py microservices/
	isort modules/ tests/ main.py application.py microservices/

clean:
	python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"

pre-commit:
	pre-commit run --all-files
