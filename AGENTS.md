# Developer Agent Guide for octoDNS EdgeCenter Provider

This repository contains the EdgeCenter (formerly G-Core) provider for octoDNS. It enables planning, syncing, and applying DNS record states to the EdgeCenter DNS v2 platform, with support for advanced dynamic filter chains and check monitoring.

> [!IMPORTANT]
> **Core Workflow and Guidelines**
>
> All agents working on this repository must read and follow the general instructions and workflow guidelines defined in the core octoDNS `AGENTS.md` file.
> - **Local check**: Look for the file at `../octodns/AGENTS.md`.
> - **Remote check**: If the local file is not available, fetch it from GitHub: [octoDNS Core AGENTS.md](https://github.com/octodns/octodns/raw/refs/heads/main/AGENTS.md).
>
> You must align your code structure, style, pull request guidelines, and overall development workflows with the instructions specified there.

## Repository & Module Information

### Key Components

- **Provider Class**: [EdgeCenterProvider](file:///home/ross/octodns/octodns-edgecenter/octodns_edgecenter/__init__.py#L962-L968) (inheriting from [_BaseProvider](file:///home/ross/octodns/octodns-edgecenter/octodns_edgecenter/__init__.py#L415-L961), defined in [octodns_edgecenter/__init__.py](file:///home/ross/octodns/octodns-edgecenter/octodns_edgecenter/__init__.py)). This is the core provider implementing dynamic routing filter mapping.
- **Client Class**: [EdgeCenterClient](file:///home/ross/octodns/octodns-edgecenter/octodns_edgecenter/__init__.py#L38-L157) communicates with the EdgeCenter API.
- **Authentication**: Supports static token-based authentication via `token` and `token_type` headers, or dynamic authentication using `login` and `password` which calls POST to `auth/jwt/login` to obtain an access JWT token.
- **Endpoints**: Configured via the `url` (defaults to `https://api.edgecenter.ru/dns/v2`) and `auth_url` (defaults to `https://api.edgecenter.ru/iam`) parameters.

### Key Workflows & Features

1. **Supported Record Types**: `A`, `AAAA`, `ALIAS`, `CAA`, `CNAME`, `DNAME`, `MX`, `NS`, `TXT`, `SRV`, `SSHFP`.
2. **Dynamic Routing Support**: Fully supported (`SUPPORTS_DYNAMIC=True`, `SUPPORTS_GEO=True`) using EdgeCenter API filter properties:
   - `geodns`: Geolocation-based DNS routing.
   - `is_healthy`: Active check failover monitoring.
   - `weighted_shuffle`: Weighted load balancing routing.
   - `first_n`: Restricts the returned response values.
3. **Failover Configuration**: Maps octoDNS health checks (`healthcheck_protocol`, `healthcheck_port`, etc.) to EdgeCenter API monitoring configurations (supports `HTTP`, `HTTPS`, `TCP`, `UDP`, and `ICMP` checks).
4. **Pool Value Status**: Supported (`SUPPORTS_POOL_VALUE_STATUS=True`).
5. **Minimum TTL**: Clamps the minimum TTL to `60` seconds (`MIN_TTL = 60`).

## Development & Testing

- **Setup Script**: Run `./script/bootstrap` to create a virtual environment, install dependencies (including `black`, `isort`, `pyflakes`, and `pytest`), and configure pre-commit hooks.
- **Test Suite**: Run unit tests using `pytest` via `./script/test` (or `pytest tests/`). Test files are located in [tests/](file:///home/ross/octodns/octodns-edgecenter/tests).
- **Code Coverage**: Verify code coverage using `./script/coverage`.

## Key Constraints & Behaviors

- **Python Version**: Targets Python `>=3.9`.
- **Formatting**: Code formatting is enforced via `black` (version `>=26.0.0,<27.0.0`) and `isort`.
