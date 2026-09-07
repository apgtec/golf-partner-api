# Bolt6 golf data integration

Bolt6 publishes golf ball positions during play. This package is everything you need to
integrate: send us the scorecard and stroke state, receive ball, pin and tee positions.

## What each side provides

| | You provide | Bolt6 provides |
|---|---|---|
| Tournament and round structure | ✔ | |
| Course, holes, par, hole length | ✔ | |
| Groups, players, tee times | ✔ | |
| Strokes, and stroke state if you have it | ✔ | |
| **Ball positions** | | ✔ |
| **Pin and tee positions** | | ✔ |

Distances — to the pin, travelled, to the fairway edge — you compute from the positions we publish.
They are all in one flat metric coordinate system, so it is Euclidean arithmetic:
[Computing distances](integration.md#8-computing-distances-on-your-side).

## Package contents

| File | What it is |
|---|---|
| this page | overview, prerequisites, quickstart, checklist |
| [Integration guide](integration.md) | every use case end to end, with request/response examples |
| [Reference](reference.md) | normative semantics: coordinates, units, time, delivery, auth, errors |
| [`partner-schema.gql`](schema.md) | the contract, as GraphQL SDL |
| [Operations](operations.md) | ready-to-use operation documents |

Read this page, then the [Integration guide](integration.md). Use the [Reference](reference.md) to settle details.

## The five things that catch people out

Worth knowing before you write any code.

1. **Ball coordinates can be null.** When we know the ball is in the left greenside bunker but have
   not yet fixed its coordinates, you get `state: ZONED`, a populated `surface`, and
   `easting`/`northing`/`elevation` all null. This is the normal state of every stroke before the
   ball is located — not an error, not rare. See
   [Zone-only positions](integration.md#6-handling-zone-only-positions).
2. **Coordinates are UTM metres, not latitude/longitude.** One integer (`utmZone`) plus a hemisphere
   defines the horizontal system, `verticalEpsg` the vertical. See
   [Coordinates](reference.md#2-coordinates).
3. **Everything is metric.** Hole length in metres, not yards; values are stored exactly as sent.
4. **Positions get corrected and withdrawn.** There is one position per stroke; a correction arrives
   as the same `strokeId` with a higher `revision`, a withdrawal with `retracted: true`. You must
   handle both. See
   [Corrections and retractions](integration.md#7-corrections-and-retractions).
5. **You hold the cursor.** We keep no per-consumer delivery state. Persist the highest `revision`
   you have processed and resume from it. See [Delivery](reference.md#7-delivery).

## Prerequisites

- **A GraphQL client** that supports subscriptions over the `graphql-transport-ws` WebSocket
  subprotocol. Widely available: `graphql-ws` (JS/TS), `gql` with `websockets` (Python),
  Apollo, urql.
- **Credentials.** We issue you a bearer JWT during onboarding.
- **Your own stable ids** for tournament, course, round, group, player and stroke, sent as
  `externalId` when you create each one. Use whatever key space you already have. Creation is an
  idempotent upsert on `externalId`, so retries are safe.
- **A map from your ids to ours.** Every write returns the Bolt6 ids of what it stored, paired with
  your `externalId`; every later reference — reads, strokes, retractions — uses the Bolt6 id. See
  [Ids](integration.md#ids-ours-for-references-yours-for-creation).
- **Durable storage for one integer** per round — the last `revision` you processed.
- **The course's UTM zone.** Supply it in `upsertCourse`. If you do not know it, derive it from the
  course's longitude: `zone = floor((longitude + 180) / 6) + 1`.

## Endpoint

```
wss://<tour>.hasura.bolt6.cloud/v1/graphql   subscriptions
https://<tour>.hasura.bolt6.cloud/v1/graphql queries and mutations
```

You are given the exact host for your tour. One deployment per tour, so there is no tenant field on
the wire.

Authenticate with `Authorization: Bearer <jwt>` on both. Details in
[Authentication](reference.md#8-authentication).

## Quickstart

The fastest end-to-end check is to create a tournament and read it back — it exercises
authentication, a write, the id handshake, and a read in two calls.

```bash
curl -s https://<tour>.hasura.bolt6.cloud/v1/graphql \
  -H "Authorization: Bearer $BOLT6_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "mutation($input: TournamentInput!) { upsertTournament(input: $input) { accepted message ids { kind externalId id } } }",
    "variables": { "input": { "externalId": "T-2026-07", "name": "Sydney Invitational" } }
  }'
```

```json
{
  "data": {
    "upsertTournament": {
      "accepted": true,
      "message": null,
      "ids": [ { "kind": "TOURNAMENT", "externalId": "T-2026-07", "id": "88" } ]
    }
  }
}
```

That `id: "88"` is the pattern for the whole integration: you sent your id, we returned ours, and
from now on you refer to this tournament as `88`. Read it back:

```bash
curl -s https://<tour>.hasura.bolt6.cloud/v1/graphql \
  -H "Authorization: Bearer $BOLT6_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "query($id: ID!) { tournament(id: $id) { id externalId name } }",
    "variables": { "id": "88" }
  }'
```

```json
{ "data": { "tournament": { "id": "88", "externalId": "T-2026-07", "name": "Sydney Invitational" } } }
```

The rest of setup follows the same handshake — course, then rounds, then groups — each returning the
ids the next step needs ([Integration guide](integration.md#ids-ours-for-references-yours-for-creation)).
Once rounds exist, `course(roundId:)` gives you `epsg: 32756` and `verticalEpsg: 3855`, the
coordinate systems every position is expressed in.

Once play starts, positions look like this:

```bash
curl -s https://<tour>.hasura.bolt6.cloud/v1/graphql \
  -H "Authorization: Bearer $BOLT6_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "query($roundId: ID!, $hole: Int) { ballPositions(roundId: $roundId, hole: $hole) { revision strokeId strokeExternalId playerId playerExternalId hole strokeNum easting northing elevation surface state retracted observedAt } }",
    "variables": { "roundId": "1042", "hole": 7 }
  }'
```

```json
{
  "data": {
    "ballPositions": [
      {
        "revision": 48122,
        "strokeId": "88301",
        "strokeExternalId": "S-8E8E254E",
        "playerId": "231",
        "playerExternalId": "P-231",
        "hole": 7,
        "strokeNum": 2,
        "easting": 335230.10,
        "northing": 6247788.30,
        "elevation": 30.85,
        "surface": "OFW",
        "state": "VERIFIED",
        "retracted": false,
        "observedAt": "2026-03-14T20:16:03.076Z"
      },
      {
        "revision": 48125,
        "strokeId": "88307",
        "strokeExternalId": "S-7A1C90D2",
        "playerId": "244",
        "playerExternalId": "P-244",
        "hole": 7,
        "strokeNum": 2,
        "easting": null,
        "northing": null,
        "elevation": null,
        "surface": "OGS",
        "state": "ZONED",
        "retracted": false,
        "observedAt": "2026-03-14T20:16:41.500Z"
      }
    ]
  }
}
```

Note the second row: a real ball, in a greenside bunker, with no coordinates yet. Your renderer has
to cope with that. And note the ids: `strokeId`/`playerId` are ours, `strokeExternalId`/
`playerExternalId` are the ones you sent in `upsertStroke` and `upsertGroups` — both are on every
position, so it joins to your records with or without your id map.

For live delivery use the `ballPositionEvents` subscription rather than polling this query —
[Receiving ball positions](integration.md#5-receiving-ball-positions).

## Integration checklist

Setup, once:

- [ ] Credentials verified against the quickstart above
- [ ] Your external ids stable and unique per entity
- [ ] The Bolt6 ids from every `ids` list persisted against your external ids

Before play, in this order:

- [ ] `upsertTournament` — returns `tournamentId`
- [ ] `upsertCourse` — holes, par, hole length in **metres**, `utmZone` / `utmHemisphere`; returns `courseId`
- [ ] `upsertRounds` — returns the `roundId`s everything else is keyed by
- [ ] `upsertGroups` — groups, players, tee times; returns `groupId`s and `playerId`s
- [ ] `course` read back by `roundId`, and `epsg` / `verticalEpsg` stored

During play:

- [ ] `upsertStroke` per stroke — one call at `HIT`, or one per status change if you have pre-shot events
- [ ] `retractStroke` for anything reported in error
- [ ] `ballPositionEvents` subscribed, with `afterRevision` from durable storage
- [ ] `holeReferences` subscribed — pin positions change daily

Client correctness — the parts that break in production, not in testing:

- [ ] Null `easting`/`northing`/`elevation` render correctly
- [ ] `retracted: true` removes the position from display
- [ ] Same `strokeId` with a higher `revision` replaces, not duplicates
- [ ] Cursor persisted after processing, so a restart resumes rather than replays
- [ ] Unknown enum members do not crash the client
- [ ] `accepted: false` is logged and **not** retried unchanged
- [ ] Transport errors retried with backoff
- [ ] Round numbers ordered by `num`, not assumed to be 1..4

## Support

Contract version is in the header of `partner-schema.gql`. Quote it, plus the `roundId` and a
`revision`, in any query to us — that is enough for us to find the exact records you saw.
