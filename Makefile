.PHONY: test
test:
	uv run tox -e unit

.PHONY: integration-test
integration-test:
	uv run tox -e integration

.PHONY: lint
lint:
	uv run tox -e lint

.PHONY: format
format:
	uv run tox -e format
