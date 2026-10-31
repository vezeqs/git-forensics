.PHONY: help test validate check clean

help:
	@echo "make validate  check every SKILL.md against the spec"
	@echo "make test      run the behavioural test suite"
	@echo "make check     both"
	@echo "make clean     remove __pycache__"

validate:
	python3 tools/validate_skills.py

test:
	python3 -m unittest discover -s tests -v

check: validate test

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
