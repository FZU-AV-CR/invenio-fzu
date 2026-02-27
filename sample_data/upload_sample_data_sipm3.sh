#!/usr/bin/env bash

set -euo pipefail

# This script uploads sample data files to the Invenio instance.

cd $(dirname "$0")

# run: uvx nrp-cmd add repository  --no-verify-tls  https://127.0.0.1:5000/ physica-local
REPOSITORY=physica-local

# create a draft record
uvx nrp-cmd create record --repository $REPOSITORY --model detectors ./sipm_003.json --set sipm_003_draft


# upload a file to the draft record
file_metadata=$(cat <<EOF
{
  "description": "SiPM testing for Fermilab DUNE. Prg3, Tray000001",
  "tray": "Tray000001",
  "tray_numbers": [1],
  "measurements": ["DCR","RoomT Forward"],
  "ardu": ["ARDU 0","ARDU 1"],
  "qr": ["0000005943","0000005944"]
}
EOF
)

uvx nrp-cmd upload file @sipm_003_draft --key 02 ./sipm_003.zip "$file_metadata" --log-request --repository $REPOSITORY

# publish the record
uvx nrp-cmd publish record @sipm_003_draft --repository $REPOSITORY