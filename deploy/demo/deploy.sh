#!/bin/bash
# Ship the committed code to the demo server: upload a release to S3, then tell the server
# (through SSM, no SSH) to run server-setup.sh. Needs `aws login --profile upchirp`.
set -euo pipefail
cd "$(dirname "$0")/../.."
REGION=eu-central-1
AWS=(aws --profile upchirp --region "$REGION")
BUCKET=$(terraform -chdir=infra output -raw bucket)
INSTANCE=$(terraform -chdir=infra output -raw instance_id)

git archive --format=tar.gz -o "${TMPDIR:-/tmp}/upchirp.tar.gz" HEAD
"${AWS[@]}" s3 cp "${TMPDIR:-/tmp}/upchirp.tar.gz" "s3://$BUCKET/releases/upchirp.tar.gz"
"${AWS[@]}" s3 cp deploy/demo/server-setup.sh "s3://$BUCKET/releases/server-setup.sh"

if [ "${1:-}" = "--upload-only" ]; then exit 0; fi
"${AWS[@]}" ssm send-command --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
  --comment "upchirp deploy" --query Command.CommandId --output text \
  --parameters "commands=[\"aws s3 cp --region $REGION s3://$BUCKET/releases/server-setup.sh /root/server-setup.sh\",\"bash /root/server-setup.sh $BUCKET $REGION > /var/log/upchirp-deploy.log 2>&1\"]"
