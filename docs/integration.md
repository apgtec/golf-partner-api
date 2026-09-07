# Integration guide

Every use case, in the order you will implement them, with the payloads you send and receive.
Start with [`README.md`](index.md); settle details in [Reference](reference.md).

Examples follow one tournament through setup. Your ids are `T-2026-07`, `C-1`, `R-3`, `G-8`,
`P-231`, `S-8E8E254E`; the Bolt6 ids Bolt6 assigns to them along the way are `88`, `12`, `1042`,
`8`, `231`, `88301`. The course is in **UTM zone 56, southern hemisphere** (EPSG:32756). All
coordinates are metres.

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
| 10 | [Converting to latitude/longitude](#10-converting-to-latitudelongitude) | your side |
| 11 | [Reconnecting and resuming](#11-reconnecting-and-resuming) | your side |
| 12 | [Replay and backfill](#12-replay-and-backfill) | Bolt6 → you |
| 13 | [Error handling](#13-error-handling) | your side |

## Ids: ours for references, yours for creation

Two kinds of id appear everywhere below, and the rule is simple:

- **Anything you refer to, you refer to by its Bolt6 id** — `tournamentId`, `courseId`, `roundId`,
  `groupId`, `playerId`, `strokeId`, in writes and in reads.
- **Anything you create carries your own `externalId`.** Bolt6 stores it, uses it to make creation
  idempotent (a retry after a lost response cannot create a duplicate), and echoes it back on
  everything it publishes about that entity.

**Every write returns the Bolt6 ids of what it stored, paired with your `externalId`**, in
`ids: [{kind, externalId, id}]`. Keep that map on your side — it is the only bookkeeping this
integration asks of you, and setup produces it naturally:

```
upsertTournament  ─▶ tournamentId
upsertCourse      ─▶ courseId          (needs tournamentId)
upsertRounds      ─▶ roundIds          (needs tournamentId, courseId)
upsertGroups      ─▶ groupIds, playerIds   (needs roundId)
upsertStroke      ─▶ strokeId          (needs roundId, groupId, playerId)
```

Each step needs ids from the one before, so run setup in that order, and re-send whenever
something changes.

---

## 1. Tournament

Send once before the tournament, and again whenever status changes.

`operations/UpsertTournament.gql`

```json
{
  "input": {
    "externalId": "T-2026-07",
    "name": "Sydney Invitational",
    "status": "IN_PROGRESS",
    "startDate": "2026-03-12T00:00:00Z",
    "endDate": "2026-03-15T00:00:00Z"
  }
}
```

```json
{
  "data": {
    "upsertTournament": {
      "accepted": true,
      "message": null,
      "ids": [ { "kind": "TOURNAMENT", "externalId": "T-2026-07", "id": "88" } ],
      "rejected": []
    }
  }
}
```

`88` is your `tournamentId` from here on. `status` is free text passed through unchanged, so use
your own vocabulary consistently.

`currentRoundId` names the round in play by its Bolt6 id. You will not have round ids until
[use case 2](#2-course-and-rounds), so set it by re-sending the tournament once rounds exist — the
upsert is idempotent, so that is safe at any time.

---

## 2. Course and rounds

Two calls, in this order: the course (which declares the coordinate system), then the rounds played
on it. Send both before any stroke, and re-send whenever they change (a round opens, a playoff is
added).

`operations/UpsertCourse.gql` — with the `tournamentId` from use case 1:

```json
{
  "input": {
    "tournamentId": "88",
    "externalId": "C-1",
    "name": "Moore Park",
    "utmZone": 56,
    "utmHemisphere": "SOUTH",
    "par": 71,
    "frontPar": 35,
    "backPar": 36,
    "length": 6532.0,
    "holes": [
      { "number": 1, "par": 4, "length": 370.3 },
      { "number": 2, "par": 3, "length": 132.6 },
      { "number": 7, "par": 5, "length": 481.0 }
    ]
  }
}
```

```json
{
  "data": {
    "upsertCourse": {
      "accepted": true, "message": null,
      "ids": [ { "kind": "COURSE", "externalId": "C-1", "id": "12" } ],
      "rejected": []
    }
  }
}
```

- **`length` is metres.** `6532.0` m, not `7143` yards. It is stored verbatim, so a yardage sent
  here will be published as though it were metres.
- **`utmZone` / `utmHemisphere` are required.** Everything positional in both directions is
  expressed in this CRS. If you do not know the zone:
  `zone = floor((longitude + 180) / 6) + 1`, hemisphere from the sign of the latitude.
- Par is optional but recommended; we pass it through to downstream consumers.

Now the rounds, each pointing at a course by its Bolt6 id:

`operations/UpsertRounds.gql`

```json
{
  "input": {
    "tournamentId": "88",
    "rounds": [
      { "externalId": "R-1",  "num": 1,   "courseId": "12", "status": "COMPLETE",    "format": "STROKE" },
      { "externalId": "R-2",  "num": 2,   "courseId": "12", "status": "COMPLETE",    "format": "STROKE" },
      { "externalId": "R-3",  "num": 3,   "courseId": "12", "status": "IN_PROGRESS", "format": "STROKE" },
      { "externalId": "R-PO", "num": 301, "courseId": "12", "status": "PENDING",     "format": "STROKE", "isTeamPlayoff": true }
    ]
  }
}
```

```json
{
  "data": {
    "upsertRounds": {
      "accepted": true, "message": null,
      "ids": [
        { "kind": "ROUND", "externalId": "R-1",  "id": "1040" },
        { "kind": "ROUND", "externalId": "R-2",  "id": "1041" },
        { "kind": "ROUND", "externalId": "R-3",  "id": "1042" },
        { "kind": "ROUND", "externalId": "R-PO", "id": "1043" }
      ],
      "rejected": []
    }
  }
}
```

- **The `roundId`s are the most important ids you will store.** Every read, every group, every
  stroke is keyed by one — `1042` is round `R-3` for the rest of this guide.
- **`num` need not be `1..N`.** The playoff round is `301`. Order rounds by `num`; never index by
  it or assume a range.
- `status` and `format` are free text passed through unchanged, so use your own vocabulary
  consistently.

Read the course back by round to confirm the CRS and cache `epsg`:

`operations/GetCourse.gql` — `{ "roundId": "1042" }`

```json
{
  "data": {
    "course": {
      "id": "12", "externalId": "C-1",
      "name": "Moore Park",
      "utmZone": 56, "utmHemisphere": "SOUTH", "epsg": 32756, "verticalEpsg": 3855,
      "par": 71, "frontPar": 35, "backPar": 36, "length": 6532.0,
      "holes": [ { "number": 7, "par": 5, "length": 481.0 } ]
    }
  }
}
```

---

## 3. Groups and players

Send when the draw is published, and again on any change (a withdrawal, a tee-time delay).

`operations/UpsertGroups.gql`

```json
{
  "input": {
    "roundId": "1042",
    "groups": [
      {
        "externalId": "G-8",
        "startHole": 1,
        "startHoleOrder": 1,
        "segment": "AM",
        "teeTime": "2026-03-14T23:10:00Z",
        "teeTimeAdjusted": "2026-03-14T23:38:00Z",
        "players": [
          {
            "externalId": "P-231", "order": 1,
            "firstName": "Tom", "lastName": "Walsh",
            "country": "NIR", "hometown": "Belfast",
            "isAmateur": false, "isCaptain": true,
            "organization": "TEAM-A", "organizationName": "Team Alpha",
            "hatColor": 16711680, "shirtColor": 16777215, "pantsColor": 255
          },
          { "externalId": "P-244", "order": 2, "firstName": "Ana", "lastName": "Ruiz", "country": "ESP" }
        ]
      }
    ]
  }
}
```

```json
{
  "data": {
    "upsertGroups": {
      "accepted": true,
      "message": null,
      "ids": [
        { "kind": "GROUP",  "externalId": "G-8",   "id": "8"   },
        { "kind": "PLAYER", "externalId": "P-231", "id": "231" },
        { "kind": "PLAYER", "externalId": "P-244", "id": "244" }
      ],
      "rejected": []
    }
  }
}
```

- **Keep the `ids`.** `groupId` and `playerId` are what every `upsertStroke` needs.
- **Players are per tournament.** The same player `externalId` in another round's groups resolves
  to the same `playerId`, so the map you build in round 1 stays valid all week.
- **Colours are integers, `0xRRGGBB`.** `16711680` is `0xFF0000`, red. Send decimal integers in
  JSON, not hex strings. Alpha is not carried. They are per round, since players change outfits
  daily.
- **Partial lists are safe at the group level.** Each listed group is upserted; groups you omit are
  left untouched, so sending a short list never deletes a group. Within a group, however, the
  `players` list you send is authoritative: a player missing from it is removed from that group. A
  group that fails validation appears in `rejected` with its `externalId` and the reason; the others
  are still stored.
- `teeTime` is scheduled, `teeTimeAdjusted` is after any delay. Send both when you have them.

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
    "roundId": "1042",
    "groupId": "8",
    "playerId": "231",
    "externalId": "S-8E8E254E",
    "hole": 7,
    "holeOrder": 13,
    "strokeNum": 2,
    "kind": "NORMAL",
    "status": "OVER_THE_BALL",
    "fromSurface": "OFW",
    "club": "D",
    "createdAt": "2026-03-14T20:15:03.076Z",
    "overBallAt": "2026-03-14T20:15:33.076Z"
  }
}
```

```json
{
  "data": {
    "upsertStroke": {
      "accepted": true,
      "message": null,
      "ids": [ { "kind": "STROKE", "externalId": "S-8E8E254E", "id": "88301" } ],
      "rejected": []
    }
  }
}
```

`roundId`, `groupId` and `playerId` come from the earlier upserts; `externalId` is your own id for
this stroke, and `88301` is the `strokeId` you would use to retract it.

**The minimum stroke report** is `roundId`, `playerId`, `externalId`, `hole`, `strokeNum` and
`hitAt`. `kind` defaults to `NORMAL` and `status` to `HIT`, so a system that only knows "a shot was
played" sends exactly that and nothing more.

If you do have pre-shot events, the full lifecycle is three upserts with the same `externalId`:

| Status | When | Timestamps to include |
|---|---|---|
| `READY` | player has reached the ball | `createdAt` |
| `OVER_THE_BALL` | player is addressing it | `createdAt`, `overBallAt` |
| `HIT` | stroke played | `createdAt`, `overBallAt`, `hitAt` |

Because it is keyed on your `externalId` within the round, resending is safe and successive calls
progressively enrich one stroke. **At least one timestamp is required**; we take `hitAt`, else `overBallAt`, else
`createdAt` as the stroke time.

`holeOrder` is the position of this hole in the player's round — `13` here means the 13th hole
they played, which is hole 7 because the group started on the back nine. Omit it if you do not
track it.

Set `kind` to `PENALTY` or `DROP` when it applies, so downstream consumers can distinguish those from
a played stroke; `PROVISIONAL` is available too.

You do not need to wait for a response before sending the next status — but do check `accepted`, and
see [Error handling](#13-error-handling).

---

## 5. Receiving ball positions

Two subscriptions over the same data. Use both: one for state, one for the event log.

### `ballPositionEvents` — the event log

Every revision in order, resumable. **This is the one to build on.**

`operations/SubscribeToBallPositionEvents.gql`

```json
{ "roundId": "1042", "afterRevision": 48120, "batchSize": 50 }
```

```json
{
  "data": {
    "ballPositionEvents": [
      {
        "revision": 48122,
        "strokeId": "88301",
        "playerId": "231",
        "groupId": "8",
        "strokeExternalId": "S-8E8E254E",
        "playerExternalId": "P-231",
        "groupExternalId": "G-8",
        "strokeNum": 2,
        "strokeKind": "NORMAL",
        "hole": 7,
        "holeOrder": 13,
        "easting": 335230.10,
        "northing": 6247788.30,
        "elevation": 30.85,
        "surface": "OFW",
        "subSurface": "FR",
        "state": "VERIFIED",
        "inTheHole": false,
        "retracted": false,
        "observedAt": "2026-03-14T20:16:03.076Z",
        "recordedAt": "2026-03-14T20:16:03.410Z"
      }
    ]
  }
}
```

The consuming loop, in full:

```python
cursor = store.get_cursor(round_id) or 0        # durable, per round

async for batch in subscribe(ballPositionEvents, roundId=round_id,
                             afterRevision=cursor, batchSize=50):
    for p in batch:
        if p["retracted"]:
            view.remove(p["strokeId"])          # withdrawal
        else:
            view.upsert(p["strokeId"], p)       # first fix OR a better one
        cursor = max(cursor, p["revision"])
    store.set_cursor(round_id, cursor)          # only after processing
```

Four properties to respect:

- **Key your state on `strokeId`.** There is exactly one position per stroke; a better fix replaces
  it under the same `strokeId`, so an upsert is always the right move.
- **`revision` only ever increases**, across first fixes, corrections and retractions alike.
- **Delivery is at-least-once.** After a reconnect you may see a revision twice, so make processing
  idempotent on `(strokeId, revision)`.
- **Persist the cursor after processing, not on receipt.** Crashing between the two should replay,
  not skip.

### `ballPositions` — current state

Current best position per stroke: the set on connect, then updates. Convenient for painting a
scoreboard or a hole overview without replaying history. Filterable by `hole`.

`operations/SubscribeToBallPositions.gql`

```json
{ "roundId": "1042", "hole": 7 }
```

It does not give you an ordered log, so do not use it to drive an event pipeline — it can collapse
several changes into one delivery.

### Which positions you get

Positions derived from your own stroke reports are not published back to you; the first position you
see for a stroke is Bolt6's own. See [Which position you receive](reference.md#5-which-position-you-receive).

---

## 6. Handling zone-only positions

**The single most common integration bug.** `easting`, `northing` and `elevation` are nullable, and
null together.

```json
{
  "revision": 48125,
  "strokeId": "88307",
  "strokeExternalId": "S-7A1C90D2",
  "playerExternalId": "P-244",
  "hole": 7,
  "strokeNum": 2,
  "easting": null,
  "northing": null,
  "elevation": null,
  "surface": "OGS",
  "subSurface": null,
  "state": "ZONED",
  "retracted": false,
  "observedAt": "2026-03-14T20:16:41.500Z"
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
    view.plot(p["strokeId"], p["easting"], p["northing"], p["elevation"])
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
revision 48125  strokeId 88307  state ZONED      easting null
revision 48160  strokeId 88307  state VERIFIED   easting 335230.10   <- same stroke, better fix
```

### Retractions you receive

A withdrawn stroke's position arrives as a new revision with `retracted: true`. It is never a silent
disappearance, so a client that only ever adds rows will show a ball that is no longer in play.

```json
{ "revision": 48191, "strokeId": "88307", "retracted": true, "state": "ZONED", "surface": "OGS" }
```

Treat `retracted: true` as authoritative and remove the record.

### Retractions you send

If you reported a stroke in error, withdraw it. We mark its positions retracted and publish that
onward, so every downstream consumer learns about it.

`operations/RetractStroke.gql`

```json
{ "input": { "strokeId": "88301" } }
```

```json
{ "data": { "retractStroke": { "accepted": true, "message": null } } }
```

`strokeId` is the Bolt6 id `upsertStroke` returned — the reason to keep the id map. To *correct*
rather than withdraw a stroke, just `upsertStroke` again with the same `externalId` — no retraction
needed. Retract only when the stroke should not exist at all.

Setup data (tournament, course, groups) has no retraction: correct it by upserting again.

---

## 8. Computing distances on your side

Distances are yours to compute. Every coordinate is in one flat metric grid, so it is plain
Euclidean arithmetic — no projection library, no geodesic formula.

Ball, from `ballPositionEvents`:

```json
{ "easting": 335230.10, "northing": 6247788.30, "elevation": 30.85, "surface": "OFW" }
```

Pin for the same hole, from `holeReferences`:

```json
{ "hole": 7, "type": "PIN", "easting": 335316.84, "northing": 6247894.84, "elevation": 32.10 }
```

```python
dE = 335230.10 - 335316.84      #  -86.74 m
dN = 6247788.30 - 6247894.84    # -106.54 m
dZ = 30.85 - 32.10              #   -1.25 m

flat = math.hypot(dE, dN)                 # 137.38 m   (150.2 yd)
slope = math.sqrt(dE*dE + dN*dN + dZ*dZ)  # 137.39 m
```

So 137.38 m — 150.2 yards — to the pin. Convert for display if your audience expects yards
(`× 1.09361`); the wire stays metric.

Same arithmetic for distance travelled (previous resting position → current) and distance from the
tee (`holeReferences` `type: TEE` → ball).

**Skip strokes with null coordinates** — a `ZONED` position has no distance.

---

## 9. Pin and tee positions

Pin positions change daily, so read them per round and never cache across rounds.

`operations/SubscribeToHoleReferences.gql`

```json
{ "roundId": "1042" }
```

```json
{
  "data": {
    "holeReferences": [
      { "hole": 7, "type": "PIN", "easting": 335316.84, "northing": 6247894.84, "elevation": 32.10, "updatedAt": "2026-03-14T18:02:11.000Z" },
      { "hole": 7, "type": "TEE", "easting": 334902.55, "northing": 6247490.18, "elevation": 35.40, "updatedAt": "2026-03-14T17:44:02.000Z" }
    ]
  }
}
```

Subscribe rather than query once: a pin updated mid-round arrives as an update, and stale pin
positions silently corrupt every distance you compute. `type` is `PIN` or `TEE`; ignore any other
value a future revision adds.

---

## 10. Converting to latitude/longitude

If your downstream needs geographic coordinates, convert with any standard library using the `epsg`
from `course`. Nothing bespoke is involved — it is a published EPSG code.

```python
from pyproj import Transformer

# epsg comes from the course query: 32756 for UTM 56 South
to_wgs84 = Transformer.from_crs("EPSG:32756", "EPSG:4326", always_xy=True)

lon, lat = to_wgs84.transform(335230.10, 6247788.30)
# lat = -33.897422, lon = 151.218017
```

The pin from the previous section converts to `lat -33.896475, lon 151.218975`.

Prefer to stay in UTM where you can: distances are direct, and every round-trip through
latitude/longitude costs precision.

`elevation` is passed through unchanged and is not part of the horizontal conversion — see the
vertical datum note in [Coordinates](reference.md#2-coordinates).

---

## 11. Reconnecting and resuming

WebSockets drop. The contract is built so that costs you nothing.

```python
cursor = store.get_cursor(round_id) or 0

while running:
    try:
        async for batch in subscribe(ballPositionEvents, roundId=round_id,
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

`afterRevision: 0` replays a round from the beginning, in revision order, including every
correction and retraction. Replaying into the same idempotent handler converges on the same state.

Useful for backfilling a round you were offline for, rebuilding after a schema change on your side,
and testing against a completed round before going live.

For a completed round the `ballPositions` query with `limit`/`offset` is a cheaper way to get final
positions only, without the revision history.

---

## 13. Error handling

Two failure classes, handled differently. Getting this wrong is how integrations end up hammering
us with a payload that will never be accepted.

### Rejected payloads — do not retry unchanged

```json
{
  "data": {
    "upsertStroke": {
      "accepted": false,
      "message": "unknown roundId '9999'",
      "ids": [],
      "rejected": []
    }
  }
}
```

`accepted: false` means the payload is wrong. Retrying it unchanged will fail identically forever.
Log it, alert, fix the payload. A call-level problem — an unknown parent id — puts the reason in
`message` and stores nothing. In a batch (`upsertRounds`, `upsertGroups`) an individual bad item
appears in `rejected` with its `externalId` and reason while the rest are stored. Common causes:

| `message` | Cause |
|---|---|
| `unknown roundId` / `unknown tournamentId` / `unknown courseId` | a Bolt6 id you never received, or one from another tournament — [Ids](#ids-ours-for-references-yours-for-creation) |
| `unknown playerId` / `unknown groupId` | not returned by `upsertGroups` for this round — [use case 3](#3-groups-and-players) |
| `no stroke timestamp supplied` | none of `createdAt` / `overBallAt` / `hitAt` present |
| `duplicate hole number` | two `holes` entries with the same `number` in one `upsertCourse` — [use case 2](#2-course-and-rounds) |

### Transport and auth errors — retry with backoff

These arrive as GraphQL `errors`, not as `accepted: false`:

```json
{ "errors": [ { "message": "Could not verify JWT: JWTExpired" } ] }
```

Retry with exponential backoff and jitter. Refresh the token on an auth error rather than retrying
the same expired one.

Full semantics in [Errors](reference.md#9-errors).
