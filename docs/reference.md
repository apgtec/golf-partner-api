# Reference

Normative semantics for the Bolt6 golf data-exchange contract. Types live in
[`partner-schema.gql`](schema.md); this document carries what SDL cannot express. For
worked examples see [Integration guide](integration.md).

**Contract version 1.0.0-draft.**

## 1. Scope

Bolt6 publishes golf ball positions, plus pin and tee positions.
You publish the scorecard: tournament and round structure, course, groups, players, and stroke
state.

| | Owner | Carried by |
|---|---|---|
| Ball positions | Bolt6 | `ballPositions`, `ballPositionEvents` |
| Pin and tee positions | Bolt6 | `holeReferences` |
| Coordinate reference system | you declare, Bolt6 publishes | `Course.utmZone` |
| Course, holes, par, hole length | you | `upsertCourse` |
| Tournament and rounds | you | `upsertTournament`, `upsertRounds` |
| Groups and players | you | `upsertGroups` |
| Stroke state | you | `upsertStroke`, `retractStroke` |

### Ids

Two kinds of id, one rule: **our id for anything you refer to, your id for anything you create.**

- Bolt6 ids (`id`, `roundId`, `playerId`, …) are opaque and stable. Every reference you make — in
  reads and in writes — uses them.
- Your `externalId` is the key you give an entity when you create it. Bolt6 stores it, keys the
  idempotent upsert on it within the parent (so a retry after a lost response cannot create a
  duplicate), and echoes it on everything it publishes about that entity — `strokeExternalId`,
  `playerExternalId`, `groupExternalId` on positions, `externalId` on every read type.

Every write returns `ids: [{kind, externalId, id}]` for what it stored. Keep the map.

## 2. Coordinates

**One coordinate system: standard UTM on WGS84, in metres.** Every position — ball, pin, tee — is
`easting`, `northing`, `elevation`, all metres.

The CRS is declared once per course as `utmZone` plus `utmHemisphere`, equivalently the `epsg`
field: `32600 + zone` in the northern hemisphere, `32700 + zone` in the southern.

These are ordinary EPSG projected CRSs, so any standard geospatial library interprets them without
configuration. Zone 56 south is EPSG:32756; a position of `335230.10 E, 6247788.30 N` in it is
unambiguous.

Each course sits in a single zone, so distances within a course are plain Euclidean arithmetic —
see [use case 8](integration.md#8-computing-distances-on-your-side).

### Vertical datum

UTM is a two-dimensional projection: `epsg` defines easting and northing only. `elevation` is
declared separately, by `verticalEpsg`.

**`elevation` is orthometric height above the EGM2008 geoid — EPSG:3855 — in metres.** That is
height above mean sea level in the ordinary sense, and it is the same declaration at every venue.

Combine the two codes when you need a full 3D CRS: `epsg` for the horizontal plus `verticalEpsg` for
the vertical, e.g. EPSG:32756 + EPSG:3855.

Elevation is accurate to roughly ±1 m absolute. Differences between two Bolt6 positions —
ball-to-pin, for instance — are much tighter than that.

## 3. Units

| Quantity | Unit |
|---|---|
| Positions, elevations | metres |
| Hole and course length | metres |
| Colours | `0xRRGGBB` integer, alpha not carried |
| Timestamps | ISO 8601 UTC, explicit `Z` |

Hole length you send in `upsertCourse` is stored verbatim and not converted, so a yardage sent there
will be republished as though it were metres. Convert for display on your side
(`metres × 1.09361` for yards).

## 4. Time

Three distinct times, named separately.

| Field | Meaning |
|---|---|
| `observedAt` | when the observation was made, on the observing system's clock |
| `recordedAt` | when Bolt6 recorded it |
| `createdAt` / `overBallAt` / `hitAt` | stroke lifecycle times, supplied by you |

Format rules:

- Always UTC with a literal `Z`. Send `2026-03-14T20:16:03.076Z`, not `+00:00`.
- Fractional seconds to at most microsecond precision.

**Stroke time precedence.** When you supply more than one lifecycle time, Bolt6 takes `hitAt`, else
`overBallAt`, else `createdAt` as the stroke time. We need at least one; a stroke with none is
rejected.

## 5. Which position you receive

There is exactly one published position per stroke, identified by `strokeId`. Bolt6 may hold
several candidates for it over time; you receive the best one, and a better one arrives as a new
`revision` of the same `strokeId`. Ties break on `observedAt`, then `recordedAt`.

Positions derived from your own stroke reports are not published back to you — a stroke's first
published position is Bolt6's own. `state` tells you how much is known about it: see §6 and
[use case 6](integration.md#6-handling-zone-only-positions).

## 6. Nullability

**`easting`, `northing` and `elevation` are nullable, and null together.** `surface` is always
populated.

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
| `subscription holeReferences`, `course`, `groups` | state |
| `query *` | point-in-time read |

### Revisions

`revision` increases on **every** change to a stroke's position — first fix, better fix, correction
and retraction alike. That is what makes corrections and withdrawals deliverable through an ordered
stream.

- A **correction** is the same `strokeId` with a higher `revision`. Key your state on `strokeId`
  and upsert.
- A **retraction** is a new `revision` with `retracted: true`. Never a silent removal.

### Cursors

`ballPositionEvents` takes `afterRevision`; you pass the highest revision you have durably
processed. `0` replays the round from the beginning.

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
It is scoped to you: requests only ever see or touch tournaments you created, and a Bolt6 id from
anyone else's tournament is simply unknown to you.

Tokens expire. Refresh on an auth error rather than retrying an expired token. Rotate credentials
through the contact you were onboarded with.

## 9. Errors

Two classes, and they need different handling.

### Rejected payloads

Every write returns a `WriteResult`:

| Field | Meaning |
|---|---|
| `accepted` | `true` when nothing was rejected |
| `message` | reason for a **call-level** rejection — an unknown parent id, for instance — in which case nothing was stored |
| `ids` | every entity stored by this call: `{kind, externalId, id}` |
| `rejected` | in a batch, the individual items that were **not** stored: `{kind, externalId, message}`; the others were |

`accepted: false` means something in the payload needs changing — the same call gets the same answer.
Log, alert, fix before resending.

```json
{ "data": { "upsertStroke": { "accepted": false, "message": "unknown roundId '9999'", "ids": [], "rejected": [] } } }
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

**Treat every enum as open.** New `Surface` codes, new `PositionState` values and new `EntityKind`
members are minor revisions, so a client must not fail on an unrecognised member. Map unknown values to a fallback
and carry on.

Breaking changes are announced before the endpoint changes, with both versions served in parallel
where practical.

## 11. Vocabularies

### `Surface`

Course surface a ball lies on. Unrelated to `Course.utmZone`.

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

`NORMAL` · `PROVISIONAL` · `PENALTY` · `DROP`

### `HoleReferenceType`

`PIN` · `TEE`

### `Hemisphere`

`NORTH` · `SOUTH`

## 12. Introspection

The served schema is generated and is more verbose than `partner-schema.gql` — it carries additional
filter and ordering arguments, and root field names may differ in shape.

**`partner-schema.gql` is normative** for field names, types, nullability and semantics, and the
**mutations are final** as written. The **read and subscription operations** in `operations/` are
final in what they return and mean, but their argument syntax will differ on the served endpoint —
expect `args: {…}` wrappers, `where:` filters and a `cursor:` object on the stream, and read-side
enums that may arrive under different type names with identical values. You receive the exact
operation documents together with your credentials; send those rather than composing your own, since
your credential is restricted to that pinned set.
