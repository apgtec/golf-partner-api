# Bolt6 Golf Data API

Contract and integration guide for exchanging golf ball positions and scorecard data with Bolt6.

**Read the docs: https://apgtec.github.io/golf-partner-api/** — versioned per contract release.

| Path | What |
|---|---|
| `docs/` | the guide: start here, integration walkthrough, reference |
| `partner-schema.gql` | the normative contract, as GraphQL SDL |
| `operations/` | ready-to-use operation documents, validated against the schema in CI |

## Working on the docs

```sh
pip install "mkdocs<2" mkdocs-material mike graphql-core
python scripts/validate.py     # operations must validate against the schema
mkdocs serve                   # live preview at http://127.0.0.1:8000
```

Pushes to `main` publish the site. Each contract version is its own path (`/1.0/`), with `latest`
pointing at the newest; versions are managed with [mike](https://github.com/jimporter/mike).
