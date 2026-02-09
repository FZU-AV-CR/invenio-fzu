#!/usr/bin/env bash

set -euo pipefail

# This script uploads sample data files to the Invenio instance.

cd $(dirname "$0")

# run: uvx nrp-cmd add repository  --no-verify-tls  https://127.0.0.1:5000/ physica-local
REPOSITORY=physica-local

# create a draft record
uvx nrp-cmd create record --repository $REPOSITORY --model particles ./delphi_001.json --set deplhi_001_draft

# upload a file to the draft record
file_metadata=$(cat <<EOF
{
    "description": "DELPHI simulation data file in xsdst format",
    "number_events": 999
}
EOF
)
uvx nrp-cmd upload file @deplhi_001_draft --key 01 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 02 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 03 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 04 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 05 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 06 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 07 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 08 ./delphi_001.xsdst "$file_metadata" --log-request

# publish the record
uvx nrp-cmd publish record @deplhi_001_draft