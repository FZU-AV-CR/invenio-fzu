#!/usr/bin/env bash

set -euo pipefail

# This script uploads sample data files to the Invenio instance.

cd $(dirname "$0")

# run: uvx nrp-cmd add repository  --no-verify-tls  https://127.0.0.1:5000/ physica-local
REPOSITORY=physica-local

# create a draft record
uvx nrp-cmd create record --repository $REPOSITORY --model fram ./fram_001.json --set fram_001_draft


# upload a file to the draft record
file_metadata=$(cat <<EOF
{
  "description": "Fram record"
}
EOF
)

uvx nrp-cmd upload file @fram_001_draft --key 20260304093525-219-RA.fits ./20260304093525-219-RA.fits "$file_metadata" --log-request --repository $REPOSITORY
# uvx nrp-cmd upload file @fram_002_draft --key 03 ./big.zip "$file_metadata" --log-request --repository $REPOSITORY

# publish the record
uvx nrp-cmd publish record @fram_001_draft --repository $REPOSITORY