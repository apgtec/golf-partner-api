# Bolt6 golf data integration

Bolt6 publishes golf ball positions during play. This package is everything you need to
integrate: send us the scorecard and stroke state, receive ball, pin and tee positions.

## Who provides what

| | Scoring Provider | Ball Positioning Provider |
|---|---|---|
| Tournament and round structure | ✔ | |
| Course, holes, par | ✔ | |
| Groups, players | ✔ | |
| Strokes, and stroke state if you have it | ✔ | |
| **Ball positions** | | ✔ |
| **Pin and tee positions** | | ✔ |

Distances — to the pin, travelled, to the fairway edge — you compute from the positions we publish.
They are latitude/longitude; over a course, a flat local approximation is all it takes:
[Computing distances](integration.md#8-computing-distances-on-your-side).

## Package contents

| File | What it is |
|---|---|
| this page | overview, what you'll need, quickstart, checklist |
| [Integration guide](integration.md) | every use case end to end, with request/response examples |
| [Reference](reference.md) | normative semantics: coordinates, units, time, delivery, auth, errors |
| [`partner-schema.gql`](schema.md) | the contract, as GraphQL SDL |
| [Operations](operations.md) | ready-to-use operation documents |

Read this page, then the [Integration guide](integration.md). Use the [Reference](reference.md) to settle details.

## Five things worth knowing up front

These are easier to design around now than to retrofit later.

1. **Ball coordinates can be null.** When we know the ball is in the left greenside bunker but have
   not yet fixed its coordinates, you get `state: ZONED`, a populated `surface`, and
   `lat`/`lon`/`elevation` all null. This is the normal state of every stroke before the
   ball is located — not an error, not rare. See
   [Zone-only positions](integration.md#6-handling-zone-only-positions).
2. **Coordinates are WGS84 latitude/longitude**, with `elevation` in metres. See
   [Coordinates](reference.md#2-coordinates).
3. **Everything is metric.** Elevation, and the distances you compute from positions, are metres.
4. **Positions get corrected and withdrawn.** There is one position per stroke; a correction arrives
   as the same `strokeId` with a higher `revision`, a withdrawal with `retracted: true`. Both
   arrive on the same `strokeId`, so a single handler covers them. See
   [Corrections and retractions](integration.md#7-corrections-and-retractions).
5. **You hold the cursor.** We keep no per-consumer delivery state. Persist the highest `revision`
   you have processed and resume from it. See [Delivery](reference.md#7-delivery).

## What you'll need

- **A GraphQL client** that supports subscriptions over the `graphql-transport-ws` WebSocket
  subprotocol. Widely available: `graphql-ws` (JS/TS), `gql` with `websockets` (Python),
  Apollo, urql.
- **Credentials.** We issue you a bearer JWT during onboarding.
- **Your own stable ids** for tournament, course, round, group, player and stroke, sent as
  `providerId` when you create each one, and used to refer to it from then on. Use whatever key space
  you already have. Creation is an idempotent upsert on `providerId`, so retries are safe. See
  [Ids](integration.md#ids-yours-everywhere).
- **Durable storage for one integer** per round — the last `revision` you processed.

## Endpoint

```
wss://<tour>.hasura.bolt6.cloud/v1/graphql   subscriptions
https://<tour>.hasura.bolt6.cloud/v1/graphql queries and mutations
```

We'll give you the exact host for your tour. One deployment per tour, so there is no tenant field on
the wire.

Authenticate with `Authorization: Bearer <jwt>` on both. Details in
[Authentication](reference.md#8-authentication).

## Quickstart

The fastest end-to-end check is to create a tournament and read it back — it exercises
authentication, a write and a read in two calls.

```bash
curl -s https://<tour>.hasura.bolt6.cloud/v1/graphql \
  -H "Authorization: Bearer $BOLT6_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "mutation($input: TournamentInput!) { upsertTournament(input: $input) { accepted message id } }",
    "variables": { "input": { "providerId": "T-2026-07", "name": "Sydney Invitational", "startDate": "2026-03-12", "endDate": "2026-03-15" } }
  }'
```

```json
{ "data": { "upsertTournament": { "accepted": true, "message": null, "id": 42 } } }
```

That is the pattern for the whole integration: you name everything by your own id, and refer to it by
that same id from then on. Read it back:

```bash
curl -s https://<tour>.hasura.bolt6.cloud/v1/graphql \
  -H "Authorization: Bearer $BOLT6_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "query($id: String!) { tournaments(where: {providerId: {_eq: $id}}) { providerId name startDate endDate } }",
    "variables": { "id": "T-2026-07" }
  }'
```

```json
{ "data": { "tournaments": [ { "providerId": "T-2026-07", "name": "Sydney Invitational", "startDate": "2026-03-12", "endDate": "2026-03-15" } ] } }
```

The rest of setup follows the same pattern — course, then rounds, then groups — and can go in a
single request ([Integration guide](integration.md#ids-yours-everywhere)).

Once play starts, positions look like this:

```bash
curl -s https://<tour>.hasura.bolt6.cloud/v1/graphql \
  -H "Authorization: Bearer $BOLT6_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "query($round: String!, $hole: Int!) { ballPositions(where: {round: {providerId: {_eq: $round}}, hole: {_eq: $hole}}) { revision strokeId strokeProviderId player { providerId } hole strokeNum lat lon elevation surface state retracted observedAt } }",
    "variables": { "round": "R-3", "hole": 7 }
  }'
```

```json
{
  "data": {
    "ballPositions": [
      {
        "revision": 48122,
        "strokeId": 88301,
        "strokeProviderId": "S-8E8E254E",
        "player": { "providerId": "P-231" },
        "hole": 7,
        "strokeNum": 2,
        "lat": -33.897422,
        "lon": 151.218017,
        "elevation": 30.85,
        "surface": "FWY",
        "state": "VERIFIED",
        "retracted": false,
        "observedAt": "2026-03-14T20:16:03.076+00:00"
      },
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
        "surface": "GBK",
        "state": "ZONED",
        "retracted": false,
        "observedAt": "2026-03-14T20:16:41.5+00:00"
      }
    ]
  }
}
```

Note the second row: a real ball, in a greenside bunker, with no coordinates yet. Your renderer will
meet this case often. And note the ids: `strokeId` is ours, `strokeProviderId` and `player.providerId`
are the ones you sent in `upsertStroke` and `upsertGroup`, so it joins to your records directly.

For live delivery use the `ballPositionEvents` subscription rather than polling this query —
[Receiving ball positions](integration.md#5-receiving-ball-positions).

## Integration checklist

Setup, once:

- [ ] Credentials verified against the quickstart above
- [ ] Your provider ids stable and unique per entity

Before play, in this order:

- [ ] `upsertTournament`
- [ ] `upsertCourse` — holes and par
- [ ] `upsertRound` for each round
- [ ] `upsertGroup` for each group, with its players

During play:

- [ ] `upsertStroke` per stroke — one call at `HIT`, or one per status change if you have pre-shot events
- [ ] `retractStroke` for anything reported in error
- [ ] `ballPositionEvents` subscribed, with `afterRevision` from durable storage
- [ ] `holeReferences` subscribed — pin positions change daily

Client correctness — the parts worth exercising before going live, since they rarely surface in testing:

- [ ] Null `lat`/`lon`/`elevation` render correctly
- [ ] `retracted: true` removes the position from display
- [ ] Same `strokeId` with a higher `revision` replaces, not duplicates
- [ ] Cursor persisted after processing, so a restart resumes rather than replays
- [ ] `accepted: false` is logged and **not** retried unchanged
- [ ] Transport errors retried with backoff
- [ ] Round numbers ordered by `num`, not assumed to be 1..4

## Support

Contract version is in the header of `partner-schema.gql`. Sending it along with the round's `providerId` and a
`revision` is enough for us to find the exact records you saw.
