#!/usr/bin/env bash

set -euo pipefail

# This script uploads sample data files to the Invenio instance.

cd $(dirname "$0")

# run: uvx nrp-cmd add repository  --no-verify-tls  https://127.0.0.1:5000/ physica-local
REPOSITORY=physica-local

# create a draft record
uvx nrp-cmd create record --repository $REPOSITORY --model atlas_itk ./itk_001.json --set itk_001_draft


# upload a file to the draft record
file_metadata=$(cat <<EOF
{
  "description": "ITk record"
}
EOF
)

uvx nrp-cmd upload file @itk_001_draft --key VPA56032_W05408_7_A2_CCPL_C_001.dat ./VPA56032_W05408_7_A2_CCPL_C_001.dat "$file_metadata" --log-request --repository $REPOSITORY
# uvx nrp-cmd upload file @itk_002_draft --key 03 ./big.zip "$file_metadata" --log-request --repository $REPOSITORY

# publish the record
uvx nrp-cmd publish record @itk_001_draft --repository $REPOSITORY