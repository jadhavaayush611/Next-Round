.PHONY: format lint typecheck test check

format:
	$(MAKE) -C backend format

lint:
	$(MAKE) -C backend lint

typecheck:
	$(MAKE) -C backend typecheck

test:
	$(MAKE) -C backend test

check:
	$(MAKE) -C backend check
