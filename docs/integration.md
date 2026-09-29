# Integration guide

Every use case, in the order you will implement them, with the payloads you send and receive.
Start with [`README.md`](index.md); settle details in [Reference](reference.md).

Examples follow one tournament through setup. Your ids are `T-2026-07`, `C-1`, `R-3`, `G-8`,
`P-231`, `S-8E8E254E`. The course is Moore Park, Sydney.

| | Use case | Direction |
|---|---|---|
| 1 | [Tournament](#1-tournament) | you → Bolt6 |
| 2 | [Course and rounds](#2-course-and-rounds) | you → Bolt6 |
| 3 | [Groups and players](#3-groups-and-players) | you → Bolt6 |
| 4 | [Reporting stroke state](#4-reporting-stroke-state) | you → Bolt6 |
| 5 | [Receiving ball positions](#5-receiving-ball-positions) | Bolt6 → you |
| 6 | [Handling zone-only positions](#6-handling-zone-only-positions) | Bolt6 → you |
| 7 | [Corrections and retractions](#7-corrections-and-retractions) | both |
| 8 | [Computing distances on your side](#8-computing-distances-on-your-side) | your side |
| 9 | [Pin and tee positions](#9-pin-and-tee-positions) | Bolt6 → you |
| 10 | [Converting to UTM](#10-converting-to-utm) | your side |
| 11 | [Reconnecting and resuming](#11-reconnecting-and-resuming) | your side |
| 12 | [Replay and backfill](#12-replay-and-backfill) | Bolt6 → you |
| 13 | [Error handling](#13-error-handling) | your side |

## Ids: yours everywhere

**Anything you create carries your own `providerId`, and anything you refer to, you refer to by that
same id** — in writes and in reads. Bolt6 stores it and uses it to make creation idempotent (a retry
after a lost response cannot create a duplicate).

A tournament's `providerId` is unique across your data; a course's, round's and player's within their
tournament; a group's and stroke's within their round. So references carry their parents:

```
upsertTournament  { providerId }
upsertCourse      { tournament, providerId }
upsertRound       { tournament, providerId, course }
upsertGroup       { tournament, round, providerId, players }
upsertStroke      { tournament, round, player, providerId }
```

Parents come first, so run setup in that order, and re-send whenever something changes. Nothing needs
the response of an earlier call, so several can go in one request as aliases
([`SetupRound`](operations.md#setupround)); they run in order.

---

## 1. Tournament

Send once before the tournament, and again whenever it changes.

`operations/UpsertTournament.gql`

```json
{
  "input": {
    "providerId": "T-2026-07",
    "name": "Sydney Invitational",
    "startDate": "2026-03-12",
    "endDate": "2026-03-15"
  }
}
```

```json
{ "data": { "upsertTournament": { "accepted": true, "message": null } } }
```

---

## 2. Course and rounds

Two calls, in this order: the course, then the rounds played on it. Send both before any stroke, and re-send whenever they change (a round opens, a playoff is
added).

`operations/UpsertCourse.gql`

```json
{
  "input": {
    "tournament": "T-2026-07",
    "providerId": "C-1",
    "name": "Moore Park",
    "holes": [
      { "number": 1, "par": 4 },
      { "number": 2, "par": 3 },
      { "number": 7, "par": 5 }
    ]
  }
}
```

```json
{ "data": { "upsertCourse": { "accepted": true, "message": null } } }
```

- Par is optional but recommended; we pass it through to downstream consumers.

Now the rounds, one call each, each pointing at a course by its `providerId`:

`operations/UpsertRound.gql`

```json
{ "input": { "tournament": "T-2026-07", "providerId": "R-3", "num": 3, "course": "C-1" } }
```

```json
{ "data": { "upsertRound": { "accepted": true, "message": null } } }
```

- **Every group and stroke is keyed by a round** — `R-3` for the rest of this guide.
- **`num` need not be `1..N`.** A playoff round might be `301`. Order rounds by `num`; never index by
  it or assume a range.

Read the round back, with its course and holes:

`operations/GetRound.gql` — `{ "tournament": "T-2026-07", "round": "R-3" }`

```json
{
  "data": {
    "rounds": [
      {
        "providerId": "R-3", "num": 3,
        "tournament": { "providerId": "T-2026-07", "name": "Sydney Invitational", "startDate": "2026-03-12", "endDate": "2026-03-15" },
        "course": { "providerId": "C-1", "name": "Moore Park", "holes": [ { "number": 7, "par": 5 } ] },
        "groups": []
      }
    ]
  }
}
```

---

## 3. Groups and players

Send when the draw is published, and again on any change (a withdrawal, a player moving group).

`operations/UpsertGroup.gql`, one call per group:

```json
{
  "input": {
    "tournament": "T-2026-07",
    "round": "R-3",
    "providerId": "G-8",
    "startHole": 1,
    "startHoleOrder": 1,
    "segment": "AM",
    "players": [
      { "providerId": "P-231", "order": 1, "firstName": "Tom", "lastName": "Walsh" },
      { "providerId": "P-244", "order": 2, "firstName": "Ana", "lastName": "Ruiz" }
    ]
  }
}
```

```json
{ "data": { "upsertGroup": { "accepted": true, "message": null } } }
```

- **Players are per tournament.** The same player `providerId` in another round's groups is the same
  player.
- **Groups you don't send are left untouched**, so sending only some groups never deletes one. Within
  a group, however, the `players` list you send is authoritative: a player missing from it is removed
  from that group.

---

## 4. Reporting stroke state

This is the live inbound path. At minimum, send one upsert per stroke when it is played. If your
system also has pre-shot events, send an upsert on each status change instead.

**You send stroke state, not ball position.** `fromSurface` is the surface the ball lies on; there
are no coordinate fields on this input.

`operations/UpsertStroke.gql`

```json
{
  "input": {
    "tournament": "T-2026-07",
    "round": "R-3",
    "player": "P-231",
    "providerId": "S-8E8E254E",
    "hole": 7,
    "holeOrder": 13,
    "strokeNum": 2,
    "kind": "NORMAL",
    "status": "OVER_THE_BALL",
    "fromSurface": "FWY",
    "at": "2026-03-14T20:15:33.076Z",
    "hatArgb": 16711680,
    "shirtArgb": 16777215,
    "pantsArgb": 255
  }
}
```

```json
{ "data": { "upsertStroke": { "accepted": true, "message": null } } }
```

`tournament`, `round` and `player` are the ids you sent in the earlier upserts; `providerId` is your
own id for this stroke.

**The minimum stroke report** is `tournament`, `round`, `player`, `providerId`, `hole`, `strokeNum`
and `at`. `kind` defaults to `NORMAL` and `status` to `HIT`, so a system that only knows "a shot was
played" sends exactly that and nothing more.

If you do have pre-shot events, the full lifecycle is three upserts with the same `providerId`, each
with the time (`at`) of its status:

| Status | When |
|---|---|
| `READY` | player has reached the ball |
| `OVER_THE_BALL` | player is addressing it |
| `HIT` | stroke played |

Because it is keyed on your `providerId` within the round, resending is safe and successive calls
progressively enrich one stroke: a report only changes the fields it carries. The stroke keeps the
time of its first report.

`holeOrder` is the position of this hole in the player's round — `13` here means the 13th hole
they played, which is hole 7 because the group started on the back nine. Omit it if you don't
track it.

Set `kind` to `PENALTY` or `DROP` when it applies, so downstream consumers can distinguish those from
a played stroke.

**Colours are integers, `0xRRGGBB`.** `16711680` is `0xFF0000`, red. Send decimal integers in JSON,
not hex strings. Alpha is not carried.

There's no need to wait for a response before sending the next status, though it's worth checking
`accepted` — see [Error handling](#13-error-handling).

---

## 5. Receiving ball positions

Two subscriptions over the same data. Use both: one for state, one for the event log.

### `ballPositionEvents` — the event log

Every stroke's latest revision, in revision order, resumable. **This is the one to build on.**

`operations/SubscribeToBallPositionEvents.gql`

```json
{ "tournament": "T-2026-07", "round": "R-3", "afterRevision": 48120, "batchSize": 50 }
```

```json
{
  "data": {
    "ballPositionEvents": [
      {
        "revision": 48122,
        "strokeId": 88301,
        "strokeProviderId": "S-8E8E254E",
        "strokeNum": 2,
        "strokeKind": "NORMAL",
        "hole": 7,
        "holeOrder": 13,
        "player": { "providerId": "P-231" },
        "group": { "providerId": "G-8" },
        "lat": -33.897422,
        "lon": 151.218017,
        "elevation": 30.85,
        "surface": "FWY",
        "subSurface": "FR",
        "state": "VERIFIED",
        "inTheHole": false,
        "retracted": false,
        "hatArgb": 16711680,
        "shirtArgb": 16777215,
        "pantsArgb": 255,
        "observedAt": "2026-03-14T20:16:03.076+00:00",
        "recordedAt": "2026-03-14T20:16:03.41+00:00"
      }
    ]
  }
}
```

The consuming loop, in full:

```python
cursor = store.get_cursor(round_id) or 0        # durable, per round

async for batch in subscribe(ballPositionEvents, tournament=tournament_id, round=round_id,
                             afterRevision=cursor, batchSize=50):
    for p in batch:
        if p["retracted"]:
            view.remove(p["strokeId"])          # withdrawal
        else:
            view.upsert(p["strokeId"], p)       # first fix OR a better one
        cursor = max(cursor, p["revision"])
    store.set_cursor(round_id, cursor)          # only after processing
```

Five properties to respect:

- **Key your state on `strokeId`.** There is exactly one position per stroke; a better fix replaces
  it under the same `strokeId`, so an upsert is always the right move.
- **`revision` only ever increases**, across first fixes, corrections and retractions alike.
- **You receive each stroke's latest revision.** If a position changes more than once between two
  deliveries, or while you are disconnected, only the latest revision is delivered.
- **Delivery is at-least-once.** After a reconnect you may see a revision twice, so make processing
  idempotent on `(strokeId, revision)`.
- **Persist the cursor after processing, not on receipt.** Crashing between the two should replay,
  not skip.

### `ballPositions` — current state

Current best position per stroke: the set on connect, then updates. Convenient for painting a
scoreboard or a hole overview without replaying history. Add `hole: {_eq: 7}` to its `where` to
follow one hole.

`operations/SubscribeToBallPositions.gql`

```json
{ "tournament": "T-2026-07", "round": "R-3" }
```

It isn't an ordered log, so it's not the right source for an event pipeline — it can collapse
several changes into one delivery.

### Which positions you get

Positions derived from your own stroke reports are not published back to you; the first position you
see for a stroke is Bolt6's own. See [Which position you receive](reference.md#5-which-position-you-receive).

---

## 6. Handling zone-only positions

**The single most common integration bug.** `lat`, `lon` and `elevation` are nullable, and null
together.

```json
{
  "revision": 48125,
  "strokeId": 88307,
  "strokeProviderId": "S-7A1C90D2",
  "player": { "providerId": "P-244" },
  "hole": 7,
  "strokeNum": 2,
  "lat": null,
  "lon": null,
  "elevation": null,
  "surface": "BNK",
  "subSurface": null,
  "state": "ZONED",
  "retracted": false,
  "observedAt": "2026-03-14T20:16:41.5+00:00"
}
```

This says: *the ball is in a greenside bunker; we have not fixed its coordinates.* It is a real,
current, correct position record — the normal state of a stroke between the ball coming to rest and
being located.

Read `state` first:

| `state` | Coordinates | What to do |
|---|---|---|
| `VERIFIED` | present | plot it |
| `OVERRIDE` | present | plot it; manually corrected |
| `PREDICTED` | present | plot it, optionally styled as provisional |
| `ZONED` | **all null** | show the surface — "greenside bunker" — with no map pin |

```python
if p["state"] == "ZONED":
    view.show_surface_only(p["strokeId"], p["surface"])
else:
    view.plot(p["strokeId"], p["lat"], p["lon"], p["elevation"])
```

A `ZONED` position is superseded by a `VERIFIED` one for the same `strokeId` with a higher
`revision` once the coordinates are known. Never treat null coordinates as `0` — that plots the ball at the
equator.

---

## 7. Corrections and retractions

Both directions have to handle withdrawal, because both sides make mistakes.

### Corrections you receive

A corrected position is **the same `strokeId` with a higher `revision`**. Upsert on `strokeId` and
it works; append blindly and you get duplicates.

```
revision 48125  strokeId 88307  state ZONED      lat null
revision 48160  strokeId 88307  state VERIFIED   lat -33.896551   <- same stroke, better fix
```

### Retractions you receive

A withdrawn stroke's position arrives as a new revision with `retracted: true`. It is never a silent
disappearance, so a client that only ever adds rows will show a ball that is no longer in play.

```json
{ "revision": 48191, "strokeId": 88307, "retracted": true, "state": "ZONED", "surface": "BNK" }
```

Treat `retracted: true` as authoritative and remove the record.

### Retractions you send

If you reported a stroke in error, withdraw it. We mark its positions retracted and publish that
onward, so every downstream consumer learns about it.

`operations/RetractStroke.gql`

```json
{ "input": { "tournament": "T-2026-07", "round": "R-3", "providerId": "S-8E8E254E" } }
```

```json
{ "data": { "retractStroke": { "accepted": true, "message": null } } }
```

The stroke is named by the ids you reported it with. To *correct* rather than withdraw a stroke,
just `upsertStroke` again with the same `providerId` — no retraction needed. Retract only when the stroke should not exist at all.

Setup data (tournament, course, groups) has no retraction: correct it by upserting again.

---

## 8. Computing distances on your side

Distances are yours to compute. Positions are latitude/longitude; over the size of a course a flat
local approximation is accurate to centimetres — no projection library, no geodesic formula.

Ball, from `ballPositionEvents`:

```json
{ "lat": -33.897422, "lon": 151.218017, "elevation": 30.85, "surface": "FWY" }
```

Pin for the same hole, from `holeReferences`:

```json
{ "hole": 7, "type": "PIN", "lat": -33.896475, "lon": 151.218975, "elevation": 32.10 }
```

```python
R = 6371008.8                                                  # mean Earth radius, metres
lat0 = math.radians(-33.897422)
dN = math.radians(-33.896475 - -33.897422) * R                 #  105.30 m
dE = math.radians(151.218975 - 151.218017) * R * math.cos(lat0)  #   88.42 m
dZ = 32.10 - 30.85                                             #    1.25 m

flat = math.hypot(dE, dN)                 # 137.50 m   (150.4 yd)
slope = math.sqrt(dE*dE + dN*dN + dZ*dZ)  # 137.51 m
```

So 137.50 m — 150.4 yards — to the pin. Convert for display if your audience expects yards
(`× 1.09361`); the wire stays metric.

Same arithmetic for distance travelled (previous resting position → current) and distance from the
tee (`holeReferences` `type: TEE` → ball).

**Skip strokes with null coordinates** — a `ZONED` position has no distance.

---

## 9. Pin and tee positions

Pin positions change daily, so read them per round and never cache across rounds.

`operations/SubscribeToHoleReferences.gql`

```json
{ "tournament": "T-2026-07", "round": "R-3" }
```

```json
{
  "data": {
    "holeReferences": [
      { "hole": 7, "type": "PIN", "lat": -33.896475, "lon": 151.218975, "elevation": 32.1, "updatedAt": "2026-03-14T18:02:11+00:00" },
      { "hole": 7, "type": "TEE", "lat": -33.900094, "lon": 151.214398, "elevation": 35.4, "updatedAt": "2026-03-14T17:44:02+00:00" }
    ]
  }
}
```

Subscribe rather than query once: a pin updated mid-round arrives as an update, and stale pin
positions silently corrupt every distance you compute. `type` is `PIN` or `TEE`; ignore any other
value a future revision adds.

---

## 10. Converting to UTM

If your downstream needs a projected grid, convert with any standard library. Nothing bespoke is
involved — positions are plain WGS84, EPSG:4326.

```python
from pyproj import Transformer

# Moore Park is in UTM zone 56 South: EPSG:32756
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32756", always_xy=True)

easting, northing = to_utm.transform(151.218017, -33.897422)
# easting = 335230.10, northing = 6247788.30
```

The pin from the previous section converts to `335316.84 E, 6247894.84 N`.

`elevation` is passed through unchanged and is not part of the horizontal conversion — see the
vertical datum note in [Coordinates](reference.md#2-coordinates).

---

## 11. Reconnecting and resuming

WebSockets drop. The contract is built so that costs you nothing.

```python
cursor = store.get_cursor(round_id) or 0

while running:
    try:
        async for batch in subscribe(ballPositionEvents, tournament=tournament_id, round=round_id,
                                     afterRevision=cursor, batchSize=50):
            for p in batch:
                apply(p)
                cursor = max(cursor, p["revision"])
            store.set_cursor(round_id, cursor)
    except ConnectionError:
        await asyncio.sleep(backoff())     # resume from the same cursor
```

- **Resume from your stored cursor**, not from `0` — that would replay the whole round.
- **Expect duplicates** across a reconnect; idempotent application makes them harmless.
- We hold no per-consumer state, so several of your processes can consume the same round
  concurrently with independent cursors.

If you lose the cursor, `afterRevision: 0` rebuilds state from scratch — correct, just slower.

---

## 12. Replay and backfill

`afterRevision: 0` replays a round from the beginning, in revision order: every stroke's latest
revision, retractions included. Replaying into the same idempotent handler converges on the same state.

Useful for backfilling a round you were offline for, rebuilding after a schema change on your side,
and testing against a completed round before going live.

For a completed round the `ballPositions` query with `limit`/`offset` is a cheaper way to get final
positions only, without the revision history.

---

## 13. Error handling

Two failure classes, handled differently — one is worth retrying, the other isn't.

### Rejected payloads — fix before resending

```json
{
  "data": {
    "upsertStroke": {
      "accepted": false,
      "message": "unknown round 'R-9' in tournament 'T-2026-07'"
    }
  }
}
```

`accepted: false` means something in the payload needs changing, and the same call will get the same
answer. Log it, alert, and fix before resending. The reason is in `message`, and a rejected call stores
nothing. Several calls in one request each get their own result. Common causes:

| `message` | Cause |
|---|---|
| `unknown tournament` / `unknown round` / `unknown course` | a parent not sent yet, or its `providerId` belongs to another tournament — [Ids](#ids-yours-everywhere) |
| `unknown player` | not in any group sent with `upsertGroup` for this tournament — [use case 3](#3-groups-and-players) |
| `unknown stroke` | retracting a stroke that was never reported |
| `invalid time` | `at` isn't an ISO 8601 time |
| `hole '7' is listed twice` | two `holes` entries with the same `number` in one `upsertCourse` — [use case 2](#2-course-and-rounds) |

### Transport and auth errors — retry with backoff

These arrive as GraphQL `errors`, not as `accepted: false`:

```json
{ "errors": [ { "message": "Could not verify JWT: JWTExpired" } ] }
```

Retry with exponential backoff and jitter. Get a new token on an auth error rather than retrying the
same expired one.

Full semantics in [Errors](reference.md#9-errors).
