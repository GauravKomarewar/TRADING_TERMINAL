Enforcement & Usage — Broker Session Ownership
===============================================

Purpose
-------
This document records the production rules and how to use the centralized broker session.

Rules (Production)
------------------
- Only `ShoonyaBot` (constructed in `shoonya_platform.execution.trading_bot.ShoonyaBot`) may instantiate `ShoonyaClient` and own the login/session lifecycle.
- All other runtime modules must use a provided `api_client` (should be `bot.api_proxy`) and must not call `ShoonyaClient()` or `login()` directly.
- Use `ShoonyaApiProxy` (`bot.api_proxy`) to access broker methods. The proxy serializes calls and enforces session validation.
- Tier-1 broker operations (e.g., `get_positions`, `get_limits`, `get_order_book`, `place_order`) will be validated by `ensure_session()` and will raise on unrecoverable failures (fail-hard). Do not suppress these exceptions.

How to adopt in code
---------------------
- If your module currently creates a `ShoonyaClient`, refactor to accept an `api_client` parameter in constructor or function. Example:

  def __init__(self, api_client=None):
      self.api = api_client or get_global_bot().api_proxy

- Use the proxy methods directly, e.g. `api.get_positions()` or `api.place_order(order)`.

Supervisor and background tasks
------------------------------
- Supervisors (e.g., option chain supervisors) must not call `login()` directly. Instead call `api.ensure_session()` or rely on the owner to manage login.

Testing
-------
- A new test `shoonya_platform/tests/test_api_proxy.py` validates the proxy serializes concurrent calls and calls `ensure_session()` for Tier-1 methods.
- Run tests locally with `pytest -q` from repository root.

Secrets and Deployment
----------------------
- Do not commit real credentials. Use `config_env/primary.env.example` as a template and populate your own `config_env/primary.env` which is excluded by `.gitignore`.

CI Recommendations
------------------
- Add a GitHub Actions workflow to run `pytest`, `flake8`/`ruff`, and `bandit` on PRs.
- Add a pre-commit configuration to run black/ruff and to prevent accidental commits of env files.

Contact
-------
- For questions about the enforcement rules, contact the repository owner or the team lead.
