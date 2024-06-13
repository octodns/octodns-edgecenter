#
#
#

import http
import logging
import urllib.parse
from collections import defaultdict

from requests import Session

from octodns import __VERSION__ as octodns_version
from octodns.provider import ProviderException
from octodns.provider.base import BaseProvider
from octodns.record import GeoCodes, Record

# TODO: remove __VERSION__ with the next major version release
__version__ = __VERSION__ = '0.0.2'


class EdgeCenterClientException(ProviderException):
    def __init__(self, r):
        super().__init__(r.text)


class EdgeCenterClientBadRequest(EdgeCenterClientException):
    def __init__(self, r):
        super().__init__(r)


class EdgeCenterClientNotFound(EdgeCenterClientException):
    def __init__(self, r):
        super().__init__(r)


class EdgeCenterClient(object):
    ROOT_ZONES = "zones"

    def __init__(
        self,
        log,
        api_url,
        auth_url,
        token=None,
        token_type=None,
        login=None,
        password=None,
    ):
        self.log = log
        self._session = Session()
        self._session.headers.update(
            {
                'User-Agent': f'octodns/{octodns_version} octodns-edgecenter/{__VERSION__}'
            }
        )
        self._api_url = api_url
        if token is not None and token_type is not None:
            self._session.headers.update(
                {"Authorization": f"{token_type} {token}"}
            )
        elif login is not None and password is not None:
            token = self._auth(auth_url, login, password)
            self._session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            raise ValueError("either token or login & password must be set")

    def _auth(self, url, login, password):
        # well, can't use _request, since API returns 400 if credentials
        # invalid which will be logged, but we don't want do this
        r = self._session.request(
            "POST",
            self._build_url(url, "auth", "jwt", "login"),
            json={"username": login, "password": password},
        )
        r.raise_for_status()
        return r.json()["access"]

    def _request(self, method, url, params=None, data=None):
        r = self._session.request(
            method, url, params=params, json=data, timeout=30.0
        )
        if r.status_code == http.HTTPStatus.BAD_REQUEST:
            self.log.error(
                "bad request %r has been sent to %r: %s", data, url, r.text
            )
            raise EdgeCenterClientBadRequest(r)
        elif r.status_code == http.HTTPStatus.NOT_FOUND:
            self.log.error("resource %r not found: %s", url, r.text)
            raise EdgeCenterClientNotFound(r)
        elif r.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR:
            self.log.error("server error no %r to %r: %s", data, url, r.text)
            raise EdgeCenterClientException(r)
        r.raise_for_status()
        return r

    def zone(self, zone_name):
        return self._request(
            "GET", self._build_url(self._api_url, self.ROOT_ZONES, zone_name)
        ).json()

    def zone_create(self, zone_name):
        return self._request(
            "POST",
            self._build_url(self._api_url, self.ROOT_ZONES),
            data={"name": zone_name},
        ).json()

    def zone_records(self, zone_name):
        url = self._build_url(
            self._api_url, self.ROOT_ZONES, zone_name, "rrsets"
        )
        rrsets = self._request("GET", url, params={"all": "true"}).json()
        records = rrsets["rrsets"]
        return records

    def record_create(self, zone_name, rrset_name, type_, data):
        self._request(
            "POST", self._rrset_url(zone_name, rrset_name, type_), data=data
        )

    def record_update(self, zone_name, rrset_name, type_, data):
        self._request(
            "PUT", self._rrset_url(zone_name, rrset_name, type_), data=data
        )

    def record_delete(self, zone_name, rrset_name, type_):
        self._request("DELETE", self._rrset_url(zone_name, rrset_name, type_))

    def _rrset_url(self, zone_name, rrset_name, type_):
        return self._build_url(
            self._api_url, self.ROOT_ZONES, zone_name, rrset_name, type_
        )

    @staticmethod
    def _build_url(base, *items):
        for i in items:
            base = base.strip("/") + "/"
            base = urllib.parse.urljoin(base, i)
        return base


class _BaseProvider(BaseProvider):
    SUPPORTS_GEO = False
    SUPPORTS_DYNAMIC = True
    SUPPORTS_ROOT_NS = True
    SUPPORTS = set(("A", "AAAA", "NS", "MX", "TXT", "SRV", "CNAME", "PTR"))

    def __init__(self, id, api_url, auth_url, *args, **kwargs):
        token = kwargs.pop("token", None)
        token_type = kwargs.pop("token_type", "APIKey")
        login = kwargs.pop("login", None)
        password = kwargs.pop("password", None)
        self.records_per_response = kwargs.pop("records_per_response", 1)
        self.log.debug("__init__: id=%s", id)
        super().__init__(id, *args, **kwargs)
        self._client = EdgeCenterClient(
            self.log,
            api_url,
            auth_url,
            token=token,
            token_type=token_type,
            login=login,
            password=password,
        )

        self.geo_filters = [
            {"type": "geodns"},
            {
                "type": "default",
                "limit": self.records_per_response,
                "strict": False,
            },
            {"type": "first_n", "limit": self.records_per_response},
        ]

        self.weighted_shuffle_filters = [
            {"type": "weighted_shuffle"},
            {"type": "first_n", "limit": self.records_per_response},
        ]

        self.is_healthy_filters = [{"type": "is_healthy", "strict": False}]

    def _add_dot_if_need(self, value):
        return f"{value}." if not value.endswith(".") else value

    def _build_pools(self, record, default_pool_name, value_transform_fn):
        defaults = []
        geo_sets, pool_idx = dict(), 0
        pools = defaultdict(lambda: {"values": []})
        for rr in record["resource_records"]:
            meta = rr.get("meta", {}) or {}
            value = {"value": value_transform_fn(rr["content"][0])}
            countries = meta.get("countries", []) or []
            continents = meta.get("continents", []) or []

            if meta.get("default", False):
                pools[default_pool_name]["values"].append(value)
                defaults.append(value["value"])
                continue
            elif meta.get("weight", 0) > 0:
                value_weight = {
                    "value": value_transform_fn(rr["content"][0]),
                    "weight": meta["weight"],
                }
                pools["weight"]["values"].append(value_weight)
                defaults.append(value["value"])
                continue
            # defaults is false or missing and no conties or continents
            elif len(continents) == 0 and len(countries) == 0:
                defaults.append(value["value"])
                continue

            # RR with the same set of countries and continents are
            # combined in single pool
            geo_set = frozenset(
                [GeoCodes.country_to_code(cc.upper()) for cc in countries]
            ) | frozenset(cc.upper() for cc in continents)
            if geo_set not in geo_sets:
                geo_sets[geo_set] = f"pool-{pool_idx}"
                pool_idx += 1

            pools[geo_sets[geo_set]]["values"].append(value)

        return pools, geo_sets, defaults

    def _build_rules(self, pools, geo_sets):
        rules = []
        for name, _ in pools.items():
            rule = {"pool": name}
            geo_set = next(
                (
                    geo_set
                    for geo_set, pool_name in geo_sets.items()
                    if pool_name == name
                ),
                {},
            )
            if len(geo_set) > 0:
                rule["geos"] = list(geo_set)
            rules.append(rule)

        return sorted(rules, key=lambda x: x["pool"])

    def _data_for_dynamic(self, record, value_transform_fn=lambda x: x):
        default_pool = "other"
        pools, geo_sets, defaults = self._build_pools(
            record, default_pool, value_transform_fn
        )
        if len(pools) == 0:
            raise RuntimeError(
                f"filter is enabled, but no pools where built for {record}"
            )

        # defaults can't be empty, so use first pool values
        if len(defaults) == 0:
            defaults = [
                value_transform_fn(v["value"])
                for v in next(iter(pools.values()))["values"]
            ]

        # if at least one default RR was found then setup fallback for
        # other pools to default
        if default_pool in pools:
            for pool_name, pool in pools.items():
                if pool_name == default_pool:
                    continue
                pool["fallback"] = default_pool

        rules = self._build_rules(pools, geo_sets)
        return pools, rules, defaults

    def _data_for_failover(self, record: dict) -> dict:
        record_meta = record.get("meta", {})
        failover_data = record_meta.get("failover", {})
        # to fix: missed failover attribute validation
        return failover_data

    def _data_for_single(self, _type, record):
        return {
            "ttl": record["ttl"],
            "type": _type,
            "value": self._add_dot_if_need(
                record["resource_records"][0]["content"][0]
            ),
        }

    _data_for_PTR = _data_for_single

    def _data_for_CNAME(self, _type, record):
        if record.get("filters") is None:
            return self._data_for_single(_type, record)

        pools, rules, defaults = self._data_for_dynamic(
            record, self._add_dot_if_need
        )
        failover = self._data_for_failover(record)
        return {
            "ttl": record["ttl"],
            "type": _type,
            "dynamic": {"pools": pools, "rules": rules},
            "octodns": {"failover": failover},
            "value": self._add_dot_if_need(defaults[0]),
        }

    def _data_for_multiple(self, _type, record):
        extra = dict()
        if record.get("filters") is not None:
            pools, rules, defaults = self._data_for_dynamic(record)
            failover = self._data_for_failover(record)
            extra = {
                "dynamic": {"pools": pools, "rules": rules},
                "octodns": {"failover": failover},
                "values": defaults,
            }
        else:
            extra = {
                "values": [
                    rr_value
                    for resource_record in record["resource_records"]
                    for rr_value in resource_record["content"]
                ]
            }
        return {"ttl": record["ttl"], "type": _type, **extra}

    _data_for_A = _data_for_multiple
    _data_for_AAAA = _data_for_multiple

    def _data_for_TXT(self, _type, record):
        return {
            "ttl": record["ttl"],
            "type": _type,
            "values": [
                rr_value.replace(";", "\\;")
                for resource_record in record["resource_records"]
                for rr_value in resource_record["content"]
            ],
        }

    def _data_for_MX(self, _type, record):
        return {
            "ttl": record["ttl"],
            "type": _type,
            "values": [
                dict(
                    preference=preference,
                    exchange=self._add_dot_if_need(exchange),
                )
                for preference, exchange in map(
                    lambda x: x["content"], record["resource_records"]
                )
            ],
        }

    def _data_for_NS(self, _type, record):
        return {
            "ttl": record["ttl"],
            "type": _type,
            "values": [
                self._add_dot_if_need(rr_value)
                for resource_record in record["resource_records"]
                for rr_value in resource_record["content"]
            ],
        }

    def _data_for_SRV(self, _type, record):
        return {
            "ttl": record["ttl"],
            "type": _type,
            "values": [
                dict(
                    priority=priority,
                    weight=weight,
                    port=port,
                    target=self._add_dot_if_need(target),
                )
                for priority, weight, port, target in map(
                    lambda x: x["content"], record["resource_records"]
                )
            ],
        }

    def zone_records(self, zone):
        try:
            return self._client.zone_records(zone.name[:-1]), True
        except EdgeCenterClientNotFound:
            return [], False

    def populate(self, zone, target=False, lenient=False):
        self.log.debug(
            "populate: name=%s, target=%s, lenient=%s",
            zone.name,
            target,
            lenient,
        )

        values = defaultdict(defaultdict)
        records, exists = self.zone_records(zone)
        for record in records:
            _type = record["type"].upper()
            if _type not in self.SUPPORTS:
                continue
            if self._should_ignore(record):
                continue
            rr_name = zone.hostname_from_fqdn(record["name"])
            values[rr_name][_type] = record

        before = len(zone.records)
        for name, types in values.items():
            for _type, record in types.items():
                data_for = getattr(self, f"_data_for_{_type}")
                record = Record.new(
                    zone,
                    name,
                    data_for(_type, record),
                    source=self,
                    lenient=lenient,
                )
                zone.add_record(record, lenient=lenient)

        self.log.info(
            "populate:   found %s records, exists=%s",
            len(zone.records) - before,
            exists,
        )
        return exists

    def _should_ignore(self, record):
        name = record.get("name", "name-not-defined")
        if record.get("filters") is None:
            return False

        want_filters = 0
        want_types = None

        filters = record.get("filters")
        types = [fls.get("type", "") for fls in filters]

        if "geodns" in types and "is_healthy" in types:
            want_filters = 4
            want_types = enumerate(
                ["geodns", "default", "first_n", "is_healthy"]
            )
        elif "weighted_shuffle" in types and "is_healthy" in types:
            want_filters = 3
            want_types = enumerate(
                ["weighted_shuffle", "first_n", "is_healthy"]
            )
        elif "geodns" in types:
            want_filters = 3
            want_types = enumerate(["geodns", "default", "first_n"])
        elif "weighted_shuffle" in types:
            want_filters = 2
            want_types = enumerate(["weighted_shuffle", "first_n"])
        elif "is_healthy" in types:
            want_filters = 1
            want_types = enumerate(["is_healthy"])

        if len(filters) != want_filters:
            self.log.info(
                "ignore %s has filters and their count is not %d",
                name,
                want_filters,
            )
            return True

        for i, want_type in want_types:
            if types[i] != want_type:
                self.log.info(
                    "ignore %s, filters.%d.type is %s, want %s",
                    name,
                    i,
                    types[i],
                    want_type,
                )
                return True

        limits = {fls.get("limit") for fls in filters if "limit" in fls}
        if limits and len(limits) != 1:
            self.log.info(
                "ignore %s, filters have different limit values", name
            )
            return True
        return False

    def _params_for_dymanic(self, record):
        records = []
        default_pool_found = False
        default_values = set(
            record.values if hasattr(record, "values") else [record.value]
        )
        weight = False
        if "weight" in record.dynamic.pools:
            weight = True
        for rule in record.dynamic.rules:
            meta = dict()
            # build meta tags if geos information present
            if len(rule.data.get("geos", [])) > 0:
                for geo_code in rule.data["geos"]:
                    geo = GeoCodes.parse(geo_code)

                    country = geo["country_code"]
                    continent = geo["continent_code"]
                    if country is not None:
                        meta.setdefault("countries", []).append(country)
                    else:
                        meta.setdefault("continents", []).append(continent)
            elif not weight:
                meta["default"] = True

            pool_values = set()
            pool_name = rule.data["pool"]
            for value in record.dynamic.pools[pool_name].data["values"]:
                v = value["value"]
                if weight:
                    meta = dict()
                    meta["weight"] = value["weight"]
                records.append({"content": [v], "meta": meta})
                pool_values.add(v)

            default_pool_found |= default_values == pool_values

        # if default values doesn't match any pool values, then just add this
        # values with no any metaif default values doesn't match any pool values, then just add this
        # values with no any meta
        if not default_pool_found and not weight:
            for value in default_values:
                records.append({"content": [value]})

        return records, weight

    def _params_for_failover(self, record: Record) -> dict:
        failover_data = record.octodns.get("failover", {})
        # to fix: missed failover attribute validation
        return {"meta": {"failover": failover_data}}

    def _params_for_single(self, record):
        return {
            "ttl": record.ttl,
            "resource_records": [{"content": [record.value]}],
        }

    _params_for_PTR = _params_for_single

    def _params_for_CNAME(self, record):
        extra = dict()
        if not record.dynamic:
            return self._params_for_single(record)

        records, weight = self._params_for_dymanic(record)
        filters = self.geo_filters

        if weight:
            filters = self.weighted_shuffle_filters
            records = sorted(
                records,
                key=lambda x: (x["meta"]["weight"], x['content']),
                reverse=True,
            )

        if record.octodns.get('failover'):
            filters = [*filters, *self.is_healthy_filters]
            extra.update(self._params_for_failover(record))

        extra["resource_records"] = records
        extra["filters"] = filters

        return {"ttl": record.ttl, **extra}

    def _params_for_multiple(self, record):
        extra = dict()
        if record.dynamic:
            records, weight = self._params_for_dymanic(record)
            filters = self.geo_filters

            if weight:
                filters = self.weighted_shuffle_filters
                records = sorted(
                    records,
                    key=lambda x: (x["meta"]["weight"], x['content']),
                    reverse=True,
                )

            if record.octodns.get('failover'):
                filters = [*filters, *self.is_healthy_filters]
                extra.update(self._params_for_failover(record))

            extra["resource_records"] = records
            extra["filters"] = filters
        else:
            extra["resource_records"] = [
                {"content": [value]} for value in record.values
            ]

        return {"ttl": record.ttl, **extra}

    _params_for_A = _params_for_multiple
    _params_for_AAAA = _params_for_multiple

    def _params_for_NS(self, record):
        return {
            "ttl": record.ttl,
            "resource_records": [
                {"content": [value]} for value in record.values
            ],
        }

    def _params_for_TXT(self, record):
        return {
            "ttl": record.ttl,
            "resource_records": [
                {"content": [value.replace("\\;", ";")]}
                for value in record.values
            ],
        }

    def _params_for_MX(self, record):
        return {
            "ttl": record.ttl,
            "resource_records": [
                {"content": [rec.preference, rec.exchange]}
                for rec in record.values
            ],
        }

    def _params_for_SRV(self, record):
        return {
            "ttl": record.ttl,
            "resource_records": [
                {"content": [rec.priority, rec.weight, rec.port, rec.target]}
                for rec in record.values
            ],
        }

    def _apply_create(self, change):
        self.log.info("creating: %s", change)
        new = change.new
        data = getattr(self, f"_params_for_{new._type}")(new)
        self._client.record_create(
            new.zone.name[:-1], new.fqdn, new._type, data
        )

    def _apply_update(self, change):
        self.log.info("updating: %s", change)
        new = change.new
        data = getattr(self, f"_params_for_{new._type}")(new)
        self._client.record_update(
            new.zone.name[:-1], new.fqdn, new._type, data
        )

    def _apply_delete(self, change):
        self.log.info("deleting: %s", change)
        existing = change.existing
        self._client.record_delete(
            existing.zone.name[:-1], existing.fqdn, existing._type
        )

    def _apply(self, plan):
        desired = plan.desired
        changes = plan.changes
        zone = desired.name[:-1]
        self.log.debug(
            "_apply: zone=%s, len(changes)=%d", desired.name, len(changes)
        )

        try:
            self._client.zone(zone)
        except EdgeCenterClientNotFound:
            self.log.info("_apply: no existing zone, trying to create it")
            self._client.zone_create(zone)
            self.log.info("_apply: zone has been successfully created")

        for change in changes:
            class_name = change.__class__.__name__
            getattr(self, f"_apply_{class_name.lower()}")(change)


class EdgeCenterProvider(_BaseProvider):
    def __init__(self, id, *args, **kwargs):
        self.log = logging.getLogger(f"EdgeCenterProvider[{id}]")
        api_url = kwargs.pop("url", "https://api.edgecenter.ru/dns/v2")
        auth_url = kwargs.pop("auth_url", "https://api.edgecenter.ru/iam")
        super().__init__(id, api_url, auth_url, *args, **kwargs)
