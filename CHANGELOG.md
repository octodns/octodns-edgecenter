## 1.2.0 - 2026-05-31

Minor:
* Add support for filters-only meta and RR meta pass-through
   * NOTE: extra care should be taken to review changes on records with custom meta, See EdgeCenter RR meta passthrough in the README for more information. - [#55](https://github.com/octodns/octodns-edgecenter/pull/55)

## 1.1.0 - 2026-04-03

Minor:
* Changed the order of filters to the one used in EdgeCenter DNS API - [#40](https://github.com/octodns/octodns-edgecenter/pull/40)

Patch:
* Use new [changelet](https://github.com/octodns/changelet) tooling - [#39](https://github.com/octodns/octodns-edgecenter/pull/39)

## v1.0.0 - 2025-05-03 - Long overdue 1.0

Noteworthy Changes:

* Complete removal of SPF record support, records should be transitioned to TXT
  values before updating to this version.

Changes:

* Address pending octoDNS 2.x deprecations, require minimum of 1.5.x

## v0.0.3 - 2025-01-23 - Support the ROOT

* Add SUPPORTS_ROOT_NS to enable mangement of root NS records

## v0.0.2 - 2023-02-15 - Support the filter of weight

* Added filter support with type "weighted_shuffle"

## v0.0.1 - 2023-01-11 - Moving

#### Nothworthy Changes

* Initial extraction of EdgeCenterProvider from octoDNS core

#### Stuff

Nothing
