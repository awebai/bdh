.PHONY: help build test tidy fmt clean release-build release-verify release-publish

GOCACHE ?= $(CURDIR)/.cache/go-build
GOMODCACHE ?= $(CURDIR)/.cache/go-mod
GOENV = env GOCACHE="$(GOCACHE)" GOMODCACHE="$(GOMODCACHE)"

help:
	@echo "Targets:"
	@echo "  build   Build ./bdh"
	@echo "  test    Run unit tests"
	@echo "  tidy    go mod tidy"
	@echo "  fmt     gofmt -w ./..."
	@echo "  clean   Remove built binary"
	@echo "  release-build    Test, then build immutable release stage (VERSION=X.Y.Z)"
	@echo "  release-verify   Verify staged release bytes (VERSION=X.Y.Z)"
	@echo "  release-publish  Publish staged bytes (VERSION=X.Y.Z CONFIRM=awebai/bdh@vX.Y.Z)"

build:
	$(GOENV) go build -o bdh ./cmd/bdh

test:
	$(GOENV) go test ./...

tidy:
	$(GOENV) go mod tidy

fmt:
	gofmt -w .

clean:
	rm -f bdh

release-build:
	python3 scripts/release.py build --version "$(VERSION)" $(if $(RISK_ACCEPTANCE),--risk-acceptance "$(RISK_ACCEPTANCE)",)

release-verify:
	python3 scripts/release.py verify --stage ".release-stage/v$(VERSION)"

release-publish:
	python3 scripts/release.py publish --stage ".release-stage/v$(VERSION)" --confirm "$(CONFIRM)"
