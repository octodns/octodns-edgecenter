#
#
#

from os.path import dirname, join
from unittest import TestCase
from unittest.mock import Mock, call

from requests_mock import ANY
from requests_mock import mock as requests_mock

from octodns.provider.yaml import YamlProvider
from octodns.record import Create, Delete, Record, Update
from octodns.zone import Zone

from octodns_edgecenter import (
    EdgeCenterClientBadRequest,
    EdgeCenterClientException,
    EdgeCenterClientNotFound,
    EdgeCenterProvider,
    _BaseProvider,
)


class TestEdgeCenterProvider(TestCase):
    expected = Zone("unit.tests.", [])
    source = YamlProvider("test", join(dirname(__file__), "config"))
    source.populate(expected)

    default_filters = [
        {"type": "geodns"},
        {"type": "default", "limit": 1, "strict": False},
        {"type": "first_n", "limit": 1},
    ]

    def test_populate(self):
        provider = EdgeCenterProvider("test_id", token="token")

        # TC: 400 - Bad Request.
        with requests_mock() as mock:
            mock.get(ANY, status_code=400, text='{"error":"bad body"}')

            with self.assertRaises(EdgeCenterClientBadRequest) as ctx:
                zone = Zone("unit.tests.", [])
                provider.populate(zone)
            self.assertIn('"error":"bad body"', str(ctx.exception))

        # TC: 404 - Not Found.
        with requests_mock() as mock:
            mock.get(ANY, status_code=404, text='{"error":"zone is not found"}')

            with self.assertRaises(EdgeCenterClientNotFound) as ctx:
                zone = Zone("unit.tests.", [])
                provider._client.zone(zone.name)
            self.assertIn('"error":"zone is not found"', str(ctx.exception))

        # TC: General error
        with requests_mock() as mock:
            mock.get(ANY, status_code=500, text="Things caught fire")

            with self.assertRaises(EdgeCenterClientException) as ctx:
                zone = Zone("unit.tests.", [])
                provider.populate(zone)
            self.assertEqual("Things caught fire", str(ctx.exception))

        # TC: No credentials or token error
        with requests_mock() as mock:
            with self.assertRaises(ValueError) as ctx:
                EdgeCenterProvider("test_id")
            self.assertEqual(
                "either token or login & password must be set",
                str(ctx.exception),
            )

        # TC: Auth with login password
        with requests_mock() as mock:

            def match_body(request):
                return {"username": "foo", "password": "bar"} == request.json()

            auth_url = "http://api/auth/jwt/login"
            mock.post(
                auth_url,
                additional_matcher=match_body,
                status_code=200,
                json={"access": "access"},
            )

            providerPassword = EdgeCenterProvider(
                "test_id",
                url="http://dns",
                auth_url="http://api",
                login="foo",
                password="bar",
            )
            assert mock.called

            # make sure token passed in header
            zone_rrset_url = "http://dns/zones/unit.tests/rrsets?all=true"
            mock.get(
                zone_rrset_url,
                request_headers={"Authorization": "Bearer access"},
                status_code=404,
            )
            zone = Zone("unit.tests.", [])
            assert not providerPassword.populate(zone)

        # TC: No diffs == no changes
        with requests_mock() as mock:
            base = "https://api.edgecenter.ru/dns/v2/zones/unit.tests/rrsets"
            with open("tests/fixtures/edgecenter-no-changes.json") as fh:
                mock.get(base, text=fh.read())

            zone = Zone("unit.tests.", [])
            provider.populate(zone)
            self.assertEqual(14, len(zone.records))
            self.assertEqual(
                {
                    "",
                    "_imap._tcp",
                    "_pop3._tcp",
                    "_srv._tcp",
                    "aaaa",
                    "cname",
                    "excluded",
                    "mx",
                    "ptr",
                    "sub",
                    "txt",
                    "www",
                    "www.sub",
                },
                {r.name for r in zone.records},
            )
            changes = self.expected.changes(zone, provider)
            self.assertEqual(0, len(changes))

        # TC: 4 create (dynamic) + 1 removed + 7 modified
        with requests_mock() as mock:
            base = "https://api.edgecenter.ru/dns/v2/zones/unit.tests/rrsets"
            with open("tests/fixtures/edgecenter-records.json") as fh:
                mock.get(base, text=fh.read())

            zone = Zone("unit.tests.", [])
            provider.populate(zone, lenient=True)
            self.assertEqual(17, len(zone.records))
            changes = self.expected.changes(zone, provider)
            self.assertEqual(12, len(changes))
            self.assertEqual(
                4, len([c for c in changes if isinstance(c, Create)])
            )
            self.assertEqual(
                1, len([c for c in changes if isinstance(c, Delete)])
            )
            self.assertEqual(
                7, len([c for c in changes if isinstance(c, Update)])
            )

        # TC: Ignore disabled rrset
        with requests_mock() as mock:
            base = "https://api.edgecenter.ru/dns/v2/zones/unit.tests/rrsets"
            with open("tests/fixtures/edgecenter-records.json") as fh:
                mock.get(base, text=fh.read())

            providerExludeDisabled = EdgeCenterProvider(
                "test_id", token="token", exclude_disabled=True
            )
            zone = Zone("unit.tests.", [])
            providerExludeDisabled.populate(zone, lenient=True)
            self.assertIn("disabled", [r.name for r in zone.records])
            disabled_record = next(
                filter(lambda x: x.name == 'disabled', zone.records)
            )
            self.assertIn('1.2.3.4', disabled_record.values)
            self.assertNotIn("4.3.2.1", disabled_record.values)

        # TC: no pools can be built
        with requests_mock() as mock:
            base = "https://api.edgecenter.ru/dns/v2/zones/unit.tests/rrsets"
            mock.get(
                base,
                json={
                    "rrsets": [
                        {
                            "name": "unit.tests.",
                            "type": "A",
                            "ttl": 300,
                            "filters": self.default_filters,
                            "resource_records": [{"content": ["7.7.7.7"]}],
                        }
                    ]
                },
            )

            zone = Zone("unit.tests.", [])
            with self.assertRaises(RuntimeError) as ctx:
                provider.populate(zone)

            self.assertTrue(
                str(ctx.exception).startswith(
                    "filter is enabled, but no pools where built for"
                ),
                f"{ctx.exception} - is not start from desired text",
            )

    def test_apply(self):
        provider = EdgeCenterProvider(
            "test_id", url="http://api", token="token", strict_supports=False
        )

        # TC: Zone does not exists but can be created.
        with requests_mock() as mock:
            mock.get(ANY, status_code=404, text='{"error":"zone is not found"}')
            mock.post(ANY, status_code=200, text='{"id":1234}')

            plan = provider.plan(self.expected)
            provider.apply(plan)

        # TC: Zone does not exists and can't be created.
        with requests_mock() as mock:
            mock.get(ANY, status_code=404, text='{"error":"zone is not found"}')
            mock.post(
                ANY,
                status_code=400,
                text='{"error":"parent zone is already'
                ' occupied by another client"}',
            )

            with self.assertRaises(
                (EdgeCenterClientNotFound, EdgeCenterClientBadRequest)
            ) as ctx:
                plan = provider.plan(self.expected)
                provider.apply(plan)
            self.assertIn(
                "parent zone is already occupied by another client",
                str(ctx.exception),
            )

        resp = Mock()
        resp.json = Mock()
        provider._client._request = Mock(return_value=resp)

        with open("tests/fixtures/edgecenter-zone.json") as fh:
            zone = fh.read()

        # non-existent domain
        resp.json.side_effect = [
            EdgeCenterClientNotFound(resp),  # no zone in populate
            EdgeCenterClientNotFound(resp),  # no domain during apply
            zone,
        ]
        plan = provider.plan(self.expected)

        # TC: create all
        self.assertEqual(14, len(plan.changes))
        self.assertEqual(14, provider.apply(plan))
        self.assertFalse(plan.exists)

        provider._client._request.assert_has_calls(
            [
                call(
                    "GET",
                    "http://api/zones/unit.tests/rrsets",
                    params={"all": "true"},
                ),
                call("GET", "http://api/zones/unit.tests"),
                call("POST", "http://api/zones", data={"name": "unit.tests"}),
                call(
                    "POST",
                    "http://api/zones/unit.tests/unit.tests./A",
                    data={
                        "ttl": 300,
                        "resource_records": [
                            {"content": ["1.2.3.4"]},
                            {"content": ["1.2.3.5"]},
                        ],
                    },
                ),
                call(
                    'POST',
                    'http://api/zones/unit.tests/unit.tests./NS',
                    data={
                        'ttl': 300,
                        'resource_records': [
                            {'content': ['ns1.edgedns.ru.']},
                            {'content': ['ns2.edgedns.ru.']},
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/_imap._tcp.unit.tests./SRV",
                    data={
                        "ttl": 600,
                        "resource_records": [{"content": [0, 0, 0, "."]}],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/_pop3._tcp.unit.tests./SRV",
                    data={
                        "ttl": 600,
                        "resource_records": [{"content": [0, 0, 0, "."]}],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/_srv._tcp.unit.tests./SRV",
                    data={
                        "ttl": 600,
                        "resource_records": [
                            {"content": [10, 20, 30, "foo-1.unit.tests."]},
                            {"content": [12, 20, 30, "foo-2.unit.tests."]},
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/aaaa.unit.tests./AAAA",
                    data={
                        "ttl": 600,
                        "resource_records": [
                            {
                                "content": [
                                    "2601:644:500:e210:62f8:1dff:feb8:947a"
                                ]
                            }
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/cname.unit.tests./CNAME",
                    data={
                        "ttl": 300,
                        "resource_records": [{"content": ["unit.tests."]}],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/excluded.unit.tests./CNAME",
                    data={
                        "ttl": 3600,
                        "resource_records": [{"content": ["unit.tests."]}],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/mx.unit.tests./MX",
                    data={
                        "ttl": 300,
                        "resource_records": [
                            {"content": [10, "smtp-4.unit.tests."]},
                            {"content": [20, "smtp-2.unit.tests."]},
                            {"content": [30, "smtp-3.unit.tests."]},
                            {"content": [40, "smtp-1.unit.tests."]},
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/ptr.unit.tests./PTR",
                    data={
                        "ttl": 300,
                        "resource_records": [{"content": ["foo.bar.com."]}],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/sub.unit.tests./NS",
                    data={
                        "ttl": 3600,
                        "resource_records": [
                            {"content": ["6.2.3.4."]},
                            {"content": ["7.2.3.4."]},
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/txt.unit.tests./TXT",
                    data={
                        "ttl": 600,
                        "resource_records": [
                            {"content": ["Bah bah black sheep"]},
                            {"content": ["have you any wool."]},
                            {
                                "content": [
                                    "v=DKIM1;k=rsa;s=email;h=sha256;p=A/kinda+"
                                    "of/long/string+with+numb3rs"
                                ]
                            },
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/www.unit.tests./A",
                    data={
                        "ttl": 300,
                        "resource_records": [{"content": ["2.2.3.6"]}],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/www.sub.unit.tests./A",
                    data={
                        "ttl": 300,
                        "resource_records": [{"content": ["2.2.3.6"]}],
                    },
                ),
            ]
        )
        # expected number of total calls
        self.assertEqual(17, provider._client._request.call_count)

        # TC: delete 1 and update 1
        provider._client._request.reset_mock()
        provider._client.zone_records = Mock(
            return_value=[
                {
                    "name": "www",
                    "ttl": 300,
                    "type": "A",
                    "resource_records": [{"content": ["1.2.3.4"]}],
                },
                {
                    "name": "ttl",
                    "ttl": 600,
                    "type": "A",
                    "resource_records": [{"content": ["3.2.3.4"]}],
                },
            ]
        )

        # Domain exists, we don't care about return
        resp.json.side_effect = ["{}"]

        wanted = Zone("unit.tests.", [])
        wanted.add_record(
            Record.new(
                wanted, "ttl", {"ttl": 300, "type": "A", "value": "3.2.3.4"}
            )
        )

        plan = provider.plan(wanted)
        self.assertTrue(plan.exists)
        self.assertEqual(2, len(plan.changes))
        self.assertEqual(2, provider.apply(plan))

        provider._client._request.assert_has_calls(
            [
                call("DELETE", "http://api/zones/unit.tests/www.unit.tests./A"),
                call(
                    "PUT",
                    "http://api/zones/unit.tests/ttl.unit.tests./A",
                    data={
                        "ttl": 300,
                        "resource_records": [{"content": ["3.2.3.4"]}],
                    },
                ),
            ],
            any_order=True,
        )

        # TC: create dynamics
        provider._client._request.reset_mock()
        provider._client.zone_records = Mock(return_value=[])

        # Domain exists, we don't care about return
        resp.json.side_effect = ["{}"]

        wanted = Zone("unit.tests.", [])
        wanted.add_record(
            Record.new(
                wanted,
                "geo-simple",
                {
                    "ttl": 300,
                    "type": "A",
                    "value": "3.3.3.3",
                    "dynamic": {
                        "pools": {
                            "pool-1": {
                                "fallback": "other",
                                "values": [
                                    {"value": "1.1.1.1"},
                                    {"value": "1.1.1.2"},
                                ],
                            },
                            "pool-2": {
                                "fallback": "other",
                                "values": [{"value": "2.2.2.1"}],
                            },
                            "other": {"values": [{"value": "3.3.3.3"}]},
                        },
                        "rules": [
                            {"pool": "pool-1", "geos": ["EU-RU"]},
                            {"pool": "pool-2", "geos": ["EU"]},
                            {"pool": "other"},
                        ],
                    },
                },
            )
        )
        wanted.add_record(
            Record.new(
                wanted,
                "geo-defaults",
                {
                    "ttl": 300,
                    "type": "A",
                    "value": "3.2.3.4",
                    "dynamic": {
                        "pools": {"pool-1": {"values": [{"value": "2.2.2.1"}]}},
                        "rules": [{"pool": "pool-1", "geos": ["EU"]}],
                    },
                },
                lenient=True,
            )
        )
        wanted.add_record(
            Record.new(
                wanted,
                "cname-smpl",
                {
                    "ttl": 300,
                    "type": "CNAME",
                    "value": "en.unit.tests.",
                    "dynamic": {
                        "pools": {
                            "pool-1": {
                                "fallback": "other",
                                "values": [
                                    {"value": "ru-1.unit.tests."},
                                    {"value": "ru-2.unit.tests."},
                                ],
                            },
                            "pool-2": {
                                "fallback": "other",
                                "values": [{"value": "eu.unit.tests."}],
                            },
                            "other": {"values": [{"value": "en.unit.tests."}]},
                        },
                        "rules": [
                            {"pool": "pool-1", "geos": ["EU-RU"]},
                            {"pool": "pool-2", "geos": ["EU"]},
                            {"pool": "other"},
                        ],
                    },
                },
            )
        )
        wanted.add_record(
            Record.new(
                wanted,
                "cname-dflt",
                {
                    "ttl": 300,
                    "type": "CNAME",
                    "value": "en.unit.tests.",
                    "dynamic": {
                        "pools": {
                            "pool-1": {"values": [{"value": "eu.unit.tests."}]}
                        },
                        "rules": [{"pool": "pool-1", "geos": ["EU"]}],
                    },
                },
                lenient=True,
            )
        )

        plan = provider.plan(wanted)
        self.assertTrue(plan.exists)
        self.assertEqual(4, len(plan.changes))
        self.assertEqual(4, provider.apply(plan))

        provider._client._request.assert_has_calls(
            [
                call(
                    "POST",
                    "http://api/zones/unit.tests/cname-dflt.unit.tests./CNAME",
                    data={
                        "ttl": 300,
                        "filters": self.default_filters,
                        "resource_records": [
                            {
                                "content": ["eu.unit.tests."],
                                "meta": {"continents": ["EU"]},
                            },
                            {"content": ["en.unit.tests."]},
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/cname-smpl.unit.tests./CNAME",
                    data={
                        "ttl": 300,
                        "filters": self.default_filters,
                        "resource_records": [
                            {
                                "content": ["ru-1.unit.tests."],
                                "meta": {"countries": ["RU"]},
                            },
                            {
                                "content": ["ru-2.unit.tests."],
                                "meta": {"countries": ["RU"]},
                            },
                            {
                                "content": ["eu.unit.tests."],
                                "meta": {"continents": ["EU"]},
                            },
                            {
                                "content": ["en.unit.tests."],
                                "meta": {"default": True},
                            },
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/geo-defaults.unit.tests./A",
                    data={
                        "ttl": 300,
                        "filters": self.default_filters,
                        "resource_records": [
                            {
                                "content": ["2.2.2.1"],
                                "meta": {"continents": ["EU"]},
                            },
                            {"content": ["3.2.3.4"]},
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/unit.tests/geo-simple.unit.tests./A",
                    data={
                        "ttl": 300,
                        "filters": self.default_filters,
                        "resource_records": [
                            {
                                "content": ["1.1.1.1"],
                                "meta": {"countries": ["RU"]},
                            },
                            {
                                "content": ["1.1.1.2"],
                                "meta": {"countries": ["RU"]},
                            },
                            {
                                "content": ["2.2.2.1"],
                                "meta": {"continents": ["EU"]},
                            },
                            {"content": ["3.3.3.3"], "meta": {"default": True}},
                        ],
                    },
                ),
            ]
        )

    def test_provider_hierarchy(self):
        provider = EdgeCenterProvider("test_id", token="token")
        self.assertIsInstance(provider, _BaseProvider)


class TestEdgeCenterProviderWeighted(TestCase):
    expected = Zone("un.test.", [])
    source = YamlProvider("test2", join(dirname(__file__), "config"))
    source.populate(expected)

    weighted_shuffle_filters = [
        {"type": "weighted_shuffle"},
        {"type": "first_n", "limit": 1},
    ]

    def test_populate(self):
        provider = EdgeCenterProvider("test_id", token="token")

        # TC: 400 - Bad Request.
        with requests_mock() as mock:
            mock.get(ANY, status_code=400, text='{"error":"bad body"}')

            with self.assertRaises(EdgeCenterClientBadRequest) as ctx:
                zone = Zone("un.test.", [])
                provider.populate(zone)
            self.assertIn('"error":"bad body"', str(ctx.exception))

        # TC: No diffs == no changes
        with requests_mock() as mock:
            base = "https://api.edgecenter.ru/dns/v2/zones/un.test/rrsets"
            with open("tests/fixtures/edgecenter-no-changes-weight.json") as fh:
                mock.get(base, text=fh.read())

            zone = Zone("un.test.", [])
            provider.populate(zone)
            self.assertEqual(11, len(zone.records))
            self.assertEqual(
                {
                    "",
                    "00.img",
                    "01.img",
                    "02.img",
                    "03.img",
                    "04.img",
                    "o00.img",
                    "o01.img",
                    "o02.img",
                    "o03.img",
                    "o04.img",
                },
                {r.name for r in zone.records},
            )
            changes = self.expected.changes(zone, provider)
            self.assertEqual(0, len(changes))

        # TC: 1 create (dynamic) + 1 removed + 1 modified
        with requests_mock() as mock:
            base = "https://api.edgecenter.ru/dns/v2/zones/un.test/rrsets"
            with open("tests/fixtures/edgecenter-records-weighted.json") as fh:
                mock.get(base, text=fh.read())

            zone = Zone("un.test.", [])
            provider.populate(zone)
            self.assertEqual(11, len(zone.records))
            changes = self.expected.changes(zone, provider)
            self.assertEqual(3, len(changes))
            self.assertEqual(
                1, len([c for c in changes if isinstance(c, Create)])
            )
            self.assertEqual(
                1, len([c for c in changes if isinstance(c, Delete)])
            )
            self.assertEqual(
                1, len([c for c in changes if isinstance(c, Update)])
            )

        # TC: no pools can be built
        with requests_mock() as mock:
            base = "https://api.edgecenter.ru/dns/v2/zones/un.test/rrsets"
            mock.get(
                base,
                json={
                    "rrsets": [
                        {
                            "name": "un.test",
                            "type": "A",
                            "ttl": 60,
                            "filters": self.weighted_shuffle_filters,
                            "resource_records": [{"content": ["7.7.7.7"]}],
                        }
                    ]
                },
            )

            zone = Zone("un.test.", [])
            with self.assertRaises(RuntimeError) as ctx:
                provider.populate(zone)

            self.assertTrue(
                str(ctx.exception).startswith(
                    "filter is enabled, but no pools where built for"
                ),
                f"{ctx.exception} - is not start from desired text",
            )

    def test_apply(self):
        provider = EdgeCenterProvider(
            "test_id", url="http://api", token="token", strict_supports=False
        )

        resp = Mock()
        resp.json = Mock()
        provider._client._request = Mock(return_value=resp)

        # TC: create dynamics
        provider._client._request.reset_mock()
        provider._client.zone_records = Mock(return_value=[])

        # Domain exists, we don't care about return
        resp.json.side_effect = ["{}"]

        wanted = Zone("un.test.", [])
        wanted.add_record(
            Record.new(
                wanted,
                "weight-simple",
                {
                    "ttl": 300,
                    "type": "A",
                    "value": "3.3.3.3",
                    "dynamic": {
                        "pools": {
                            "weight": {
                                "values": [
                                    {"value": "3.3.3.3", "weight": 2},
                                    {"value": "2.3.3.3", "weight": 1},
                                    {"value": "1.3.3.3", "weight": 5},
                                ]
                            }
                        },
                        "rules": [{"pool": "weight"}],
                    },
                },
            )
        )
        wanted.add_record(
            Record.new(
                wanted,
                "weight-cname-smpl",
                {
                    "ttl": 300,
                    "type": "CNAME",
                    "value": "en.un.test.",
                    "dynamic": {
                        "pools": {
                            "weight": {
                                "values": [
                                    {"value": "ru-1.un.test.", "weight": 2},
                                    {"value": "ru-2.un.test.", "weight": 1},
                                    {"value": "eu.un.test.", "weight": 5},
                                ]
                            }
                        },
                        "rules": [{"pool": "weight"}],
                    },
                },
            )
        )

        plan = provider.plan(wanted)
        self.assertTrue(plan.exists)
        self.assertEqual(2, len(plan.changes))
        self.assertEqual(2, provider.apply(plan))

        provider._client._request.assert_has_calls(
            [
                call(
                    "POST",
                    "http://api/zones/un.test/weight-cname-smpl.un.test./CNAME",
                    data={
                        "ttl": 300,
                        "filters": self.weighted_shuffle_filters,
                        "resource_records": [
                            {"content": ["eu.un.test."], "meta": {"weight": 5}},
                            {
                                "content": ["ru-1.un.test."],
                                "meta": {"weight": 2},
                            },
                            {
                                "content": ["ru-2.un.test."],
                                "meta": {"weight": 1},
                            },
                        ],
                    },
                ),
                call(
                    "POST",
                    "http://api/zones/un.test/weight-simple.un.test./A",
                    data={
                        "ttl": 300,
                        "filters": self.weighted_shuffle_filters,
                        "resource_records": [
                            {"content": ["1.3.3.3"], "meta": {"weight": 5}},
                            {"content": ["3.3.3.3"], "meta": {"weight": 2}},
                            {"content": ["2.3.3.3"], "meta": {"weight": 1}},
                        ],
                    },
                ),
            ]
        )
