## EdgeCenter DNS v2 API provider for octoDNS

An [octoDNS](https://github.com/octodns/octodns/) provider that targets [EdgeCenter DNS](https://edgecenter.ru/dns/).

### Installation

#### Command line

```
pip install octodns-edgecenter
```

#### requirements.txt/setup.py

Pinning specific versions or SHAs is recommended to avoid unplanned upgrades.

##### Versions

```
# Start with the latest versions and don't just copy what's here
octodns==0.9.14
octodns-edgecenter==0.0.2
```

##### SHAs

```
# Start with the latest/specific versions and don't just copy what's here
-e git+https://git@github.com/octodns/octodns.git@9da19749e28f68407a1c246dfdf65663cdc1c422#egg=octodns
-e git+https://git@github.com/octodns/octodns-edgecenter.git@ec9661f8b335241ae4746eea467a8509205e6a30#egg=octodns_edgecenter
```

### Configuration


#### EdgeCenterProvider

```yaml
providers:
  ec:
    class: octodns_edgecenter.EdgeCenterProvider
    # Your API key
    token: env/EC_TOKEN
    token_type: APIKey
    # or login + password
    #login: env/EC_LOGIN
    #password: env/EC_PASSWORD
    #auth_url: https://api.edgecenter.ru/iam
    #url: https://api.edgecenter.ru/dns/v2
    #records_per_response: 1
```

### Support Information

#### Records

Supports A, AAAA, NS, MX, TXT, SRV, CNAME, and PTR

#### Dynamic

Supports dynamic records.

#### Filters

Supports filter weight of records type A, AAAA, and CNAME (weighted_shuffle)

You need to use the weight pool:

```yaml
---
'':
  # This is a dynamic record when used with providers that support it
  dynamic:
    # These are the pools of records that can be referenced and thus used by rules
    pools:
      weight:
        # Implicit weight to the weight pool (below)
        values:
        - value: 5.5.5.5
          weight: 25
        - value: 6.6.6.6
        - value: 7.7.7.7
          weight: 75
    # Rules that assign queries to pools
    rules:
    # No geos means match all queries
    - pool: weight
  ttl: 60
  type: A
  # These values become a non-healthchecked default pool
  values:
  - 5.5.5.5
  - 6.6.6.6
  - 7.7.7.7
```
```json
{
    "rrsets": [
        {
            "name": "your.zone.",
            "type": "A",
            "ttl": 60,
            "filters": [
                {
                    "type": "weighted_shuffle"
                },
                {
                    "limit": 1,
                    "type": "first_n"
                }
            ],
            "resource_records": [
                {
                    "content": [
                        "7.7.7.7"
                    ],
                    "meta": {
                        "weight": 75
                    }
                },
                {
                    "content": [
                        "6.6.6.6"
                    ],
                    "meta": {
                        "weight": 1
                    }
                },
                {
                    "content": [
                        "5.5.5.5"
                    ],
                    "meta": {
                        "weight": 25
                    }
                }
            ]
        }
     ]
}

```

### Development

See the [/script/](/script/) directory for some tools to help with the development process. They generally follow the [Script to rule them all](https://github.com/github/scripts-to-rule-them-all) pattern. Most useful is `./script/bootstrap` which will create a venv and install both the runtime and development related requirements. It will also hook up a pre-commit hook that covers most of what's run by CI.
