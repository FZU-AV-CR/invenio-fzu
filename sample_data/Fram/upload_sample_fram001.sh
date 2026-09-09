#!/usr/bin/env bash

set -euo pipefail

# This script uploads sample data files to the Invenio instance.

cd $(dirname "$0")

# run: uvx nrp-cmd add repository  --no-verify-tls  https://127.0.0.1:5000/ physica-local
REPOSITORY=physica-local

# create a draft record
# NOTE: fram_001.json has a top-level "community": "fram" key, but nrp-cmd
# does not read community assignment from the metadata body -- it only
# honors the --community/--workflow CLI flags (see AsyncInvenioRecordsClient.create()
# in nrp_cmd's source). Without --community here, the record is created
# with parent.workflow = null and *no* request types are applicable at all,
# which is what caused the "Request type publish_draft not found in
# applicable requests" error. Passing --community explicitly assigns the
# "community" workflow (parent.workflow = "community") to match how the
# fram community is actually configured (see invenio.cfg's CommunityWorkflow).
uvx nrp-cmd create record --repository $REPOSITORY --model fram --community fram ./fram_001.json --set fram_001_draft


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
#
# NOTE: `nrp-cmd publish record` is hardcoded to request the "publish_draft"
# request type (see nrp_cmd/async_client/invenio/records.py's publish()),
# which only exists for the "individual" (non-community) workflow. Records
# created inside a community (as this one is, via --community above) use
# the "community" workflow instead, whose only applicable request type is
# "community-submission" (confirmed against invenio.cfg's CommunityWorkflow
# and oarepo_config/workflows/simplified/community.py). Since the record
# owner is also the "fram" community's owner/curator, submitting this
# request auto-approves and publishes it in one step (AutoApprove()).
uvx nrp-cmd requests create community-submission @fram_001_draft --submit --repository $REPOSITORY