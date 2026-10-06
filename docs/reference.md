# Reference

Normative semantics for the Bolt6 golf data-exchange contract. Types live in
[`partner-schema.gql`](schema.md); this document carries what SDL cannot express. For
worked examples see [Integration guide](integration.md).

**Contract version 1.1.0-draft.**

## 1. Scope

Bolt6 publishes golf ball positions, plus pin and tee positions.
You publish the scorecard: tournament and round structure, course, groups, players, and stroke
state.

| | Owner | Carried by |
|---|---|---|
| Ball positions | Bolt6 | `ballPositions`, `ballPositionEvents` |
| Pin and tee positions | Bolt6 | `holeReferences` |
| Course, holes, par | you | `upsertCourse` |
| Tournament and rounds | you | `upsertTournament`, `upsertRound` |
| Groups and players | you | `upsertGroup` |
| Stroke state | you | `upsertStroke`, `retractStroke` |

### Ids

One rule: **your id for everything.**

- Your `providerId` is the key you give an entity when you create it, and the one every reference you
  make uses, in reads and in writes. Bolt6 keys the idempotent upsert on it within the parent (so a
  retry after a lost response cannot create a duplicate): a tournament's is unique across your data, a
  course's, round's and player's within their tournament, a group's and stroke's within their round.
- Bolt6's own ids (`id`, `strokeId`) are opaque and stable. Every write returns the `id` of what it
  stored, and read types carry them too, so you can keep a map if you want one; you never need them to
  write. `strokeId` is the identity of a ball position, including for strokes you never reported (their
  `strokeProviderId` is null).

## 2. Coordinates

**One coordinate system: WGS84 latitude and longitude.** Every position — ball, pin, tee — is
`lat`, `lon` in decimal degrees (EPSG:4326), plus `elevation` in metres.

These are ordinary geographic coordinates, so any standard geospatial library interprets them without
configuration. Over the size of a course, a flat local approximation gives distances to the
centimetre — see [use case 8](integration.md#8-computing-distances-on-your-side).

### Vertical datum

`elevation` is height in metres, published as Bolt6 measures it.

Elevation is accurate to roughly ±1 m absolute. Differences between two Bolt6 positions —
ball-to-pin, for instance — are much tighter than that.

## 3. Units

| Quantity | Unit |
|---|---|
| Positions, elevations | metres |
| Colours | `0xRRGGBB` integer, alpha not carried |
| Timestamps | ISO 8601 with offset; UTC in what we send |

Convert distances for display on your side (`metres × 1.09361` for yards).

## 4. Time

Three distinct times, named separately.

| Field | Meaning |
|---|---|
| `observedAt` | when the observation was made, on the observing system's clock |
| `recordedAt` | when Bolt6 recorded it |
| `at` | when a reported stroke status happened, supplied by you |

Format rules:

- Send any ISO 8601 time with an offset (`2026-03-14T20:16:03.076Z`); we store UTC and send times back as `+00:00`.
- Fractional seconds to at most microsecond precision.

**Stroke time.** A stroke keeps the `at` of its first report; each report records its own `at`.

## 5. Which position you receive

There is exactly one published position per stroke, identified by `strokeId`. Bolt6 may hold
several candidates for it over time; you receive the best one, and a better one arrives as a new
`revision` of the same `strokeId`. Ties break on `observedAt`, then `recordedAt`.

Positions derived from your own stroke reports are not published back to you — a stroke's first
published position is Bolt6's own. `state` tells you how much is known about it: see §6 and
[use case 6](integration.md#6-handling-zone-only-positions).

## 6. Nullability

**`lat`, `lon` and `elevation` are nullable, and null together.** `surface` is almost always
populated: it is null only when Bolt6 has coordinates but no surface for them.

| `state` | Coordinates |
|---|---|
| `VERIFIED` | present |
| `OVERRIDE` | present |
| `PREDICTED` | present |
| `ZONED` | **all null** |

A `ZONED` position means the surface is known and the coordinates are not. It is the normal state of
a stroke between the ball coming to rest and being located — not rare, and not an error. Branch on
`state` before reading coordinates, and never coerce null to `0`.

## 7. Delivery

| Surface | Semantics |
|---|---|
| `subscription ballPositionEvents` | queue: ordered by `revision`, resumable, at-least-once |
| `subscription ballPositions` | state: current set on connect, then updates |
| `subscription holeReferences`, `rounds`, `groups`, `players`, `tournaments` | state |
| `query *` | point-in-time read |

### Revisions

`revision` increases on **every** change to a stroke's position — first fix, better fix, correction
and retraction alike. That is what makes corrections and withdrawals deliverable through an ordered
stream.

- A **correction** is the same `strokeId` with a higher `revision`. Key your state on `strokeId`
  and upsert.
- A **retraction** is a new `revision` with `retracted: true`. Never a silent removal.
- You receive **each stroke's latest revision**: if a position changes more than once between two
  deliveries, or while you are disconnected, only the latest is delivered.

### Cursors

`ballPositionEvents` takes a cursor, `cursor: {initial_value: {revision: N}}`, and a required
`batch_size`; for `N` you pass the highest revision you have durably processed. `0` replays the round
from the beginning.

Bolt6 keeps **no per-consumer delivery state**. Consequences:

- Several of your processes can consume one round concurrently with independent cursors.
- Losing your cursor costs a replay, never data.
- Persist the cursor *after* processing a batch, so a crash replays rather than skips.

Delivery is **at-least-once**: after a reconnect you may see a revision again, so make application
idempotent on `(strokeId, revision)`.

## 8. Authentication

Bearer JWT on every request:

```
Authorization: Bearer <jwt>
```

For WebSocket subscriptions, send the same header inside the `connection_init` frame of the
`graphql-transport-ws` handshake:

```json
{ "type": "connection_init", "payload": { "headers": { "Authorization": "Bearer <jwt>" } } }
```

One credential covers both directions: it reads the published positions and sends your upserts.

Tokens expire: we send you a new one before its `exp`. On an auth error (`invalid-jwt`), get a new
token rather than retrying an expired one. Rotate credentials through the contact you were onboarded
with.

## 9. Errors

Two classes, and they need different handling.

### Rejected payloads

Every write returns a `WriteResult`:

| Field | Meaning |
|---|---|
| `accepted` | `true` when the write was stored |
| `message` | when `accepted` is `false`, the reason — an unknown parent, for instance; nothing was stored |
| `id` | Bolt6's id of what was stored — the tournament, course, round, group or stroke (`strokeId` on its ball positions); null when `accepted` is `false` |

`accepted: false` means something in the payload needs changing — the same call gets the same answer.
Log, alert, fix before resending.

```json
{ "data": { "upsertStroke": { "accepted": false, "message": "unknown round 'R-9' in tournament 'T-2026-07'", "id": null } } }
```

Several mutations in one request execute **in order, but not as one transaction**: if the third
fails, the first two are stored. Since every write is an idempotent upsert, simply retry the whole
request once the problem is fixed.

### Transport, auth and validation errors

These arrive as GraphQL `errors` and *should* be retried with exponential backoff and jitter:
connection failures, timeouts, expired or invalid tokens, rate limiting.

A GraphQL *validation* error — an unknown field or a type mismatch — is a client bug and will not
resolve on retry.

## 10. Versioning

The contract version is in the header of `partner-schema.gql` and follows semver.

- **Patch** — documentation only.
- **Minor** — additive and backward compatible: new nullable fields, new optional input fields, new
  enum members.
- **Major** — anything removed, renamed, or made stricter.

**Treat every enum as open.** New `Surface` codes and new `state` values are minor revisions, so a client must not fail on an unrecognised member. Map unknown values to a fallback
and carry on.

Breaking changes are announced before the endpoint changes, with both versions served in parallel
where practical.

## 11. Vocabularies

### `Surface`

Course surface a ball lies on.

| | | | |
|---|---|---|---|
| `TEE` Tee box | `FWY` Fairway | `INT` Intermediate | `RGH` Rough |
| `GRN` Green | `GCL` Collar / margin | `BNK` Bunker | `WTR` Water |
| `NAT` Native area | `PTH` Path | `NMS` Non-movable structure | `OTH` Other |

If your own taxonomy is coarser, map it like this for `fromSurface`:

| You have | Send |
|---|---|
| tee | `TEE` |
| fairway | `FWY` |
| first cut / intermediate rough / fairway edge | `INT` |
| rough | `RGH` |
| green | `GRN` |
| fringe / collar | `GCL` |
| any bunker | `BNK` |
| water / penalty area | `WTR` |
| native / unmaintained area | `NAT` |
| cart path / walk strip | `PTH` |
| building / wall / bridge / step | `NMS` |
| anything else | `OTH` |

### `SubSurface`

Position relative to the hole's centre line; meaningful on fairways and greens.

`FL` fairway left · `FR` fairway right · `GFL` green front left · `GFR` green front right ·
`GBL` green back left · `GBR` green back right

### `StrokeStatus`

`READY` addressed, not yet over the ball · `OVER_THE_BALL` standing over it · `HIT` played

### `StrokeKind`

`NORMAL` · `PENALTY` · `DROP`

### `HoleReference.type`

`PIN` · `TEE`

## 12. Introspection

**`partner-schema.gql` is the served schema**, generated by introspecting the endpoint with a partner
token, so introspecting it yourself gives the same schema. It carries the generated filter
(`where:`), ordering (`order_by:`) and stream cursor (`cursor:`) arguments each root field accepts.
Every document in `operations/` is validated against it.
