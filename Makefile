# The linters run at the versions pinned here, through uvx (Python tools) or
# go run (Go tools), so local runs and CI lint with the same versions.
RUFF_VERSION := 0.17.5
SHELLCHECK_VERSION := 0.11.0.1
ZIZMOR_VERSION := 1.32.0
SHFMT_VERSION := v3.14.1
ACTIONLINT_VERSION := v1.7.12

RUFF := uvx ruff@$(RUFF_VERSION)
SHELLCHECK := uvx --from shellcheck-py@$(SHELLCHECK_VERSION) shellcheck
ZIZMOR := uvx zizmor@$(ZIZMOR_VERSION)
SHFMT := go run mvdan.cc/sh/v3/cmd/shfmt@$(SHFMT_VERSION)
ACTIONLINT := go run github.com/rhysd/actionlint/cmd/actionlint@$(ACTIONLINT_VERSION)

# Every shell file git tracks or would add, and every hook.
SH_FILES := $(sort $(shell git ls-files --cached --others --exclude-standard '*.sh') $(wildcard .githooks/*))
WORKFLOWS := $(wildcard .github/workflows/*.yaml .github/workflows/*.yml)

.PHONY: help validate lint test fmt hooks

help: ## list the targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{ printf "  %-9s %s\n", $$1, $$2 }'

validate: ## lint and test, reporting both; the pre-commit hook and CI run this
	@$(MAKE) --no-print-directory -k lint test

lint: ## check Python, shell and workflow files without changing them
	$(RUFF) check .
	$(RUFF) format --check .
	$(SHELLCHECK) $(SH_FILES)
	$(SHFMT) -i 2 -d $(SH_FILES)
	$(ACTIONLINT) $(WORKFLOWS)
	$(ZIZMOR) --persona=auditor $(WORKFLOWS)

test: ## run the unit tests
	python3 -m unittest discover -p 'test_*.py'

fmt: ## rewrite Python and shell files to their formatted form
	$(RUFF) check --fix .
	$(RUFF) format .
	$(SHFMT) -i 2 -w $(SH_FILES)

hooks: ## make git run the hooks in .githooks (sets this repo's core.hooksPath)
	git config core.hooksPath .githooks
