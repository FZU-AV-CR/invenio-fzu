#!/usr/bin/env bash

set -euo pipefail

# This script uploads sample data files to the Invenio instance.

cd $(dirname "$0")

# run: uvx nrp-cmd add repository  --no-verify-tls  https://127.0.0.1:5000/ physica-local
REPOSITORY=physica-local

# create a draft record
uvx nrp-cmd create record --repository $REPOSITORY --model detectors ./sipm_002.json --set sipm_002_draft


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
uvx nrp-cmd upload file @sipm_002_draft --key 01 ./sipm_002.zip "$file_metadata" --log-request --repository $REPOSITORY
# uvx nrp-cmd upload file @deplhi_001_draft --key 02 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 03 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 04 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 05 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 06 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 07 ./delphi_001.xsdst "$file_metadata" --log-request
# uvx nrp-cmd upload file @deplhi_001_draft --key 08 ./delphi_001.xsdst "$file_metadata" --log-request

# publish the record
uvx nrp-cmd publish record @sipm_002_draft --repository $REPOSITORY