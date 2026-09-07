"""Every operation in operations/ must validate against partner-schema.gql."""
import glob, sys
from graphql import build_schema, parse, validate

schema = build_schema(open("partner-schema.gql").read())
failed = False
for path in sorted(glob.glob("operations/*.gql")):
    errors = validate(schema, parse(open(path).read()))
    print(("FAIL " if errors else "ok   ") + path)
    for e in errors:
        print("      " + e.message); failed = True
sys.exit(1 if failed else 0)
