---
phase: 2
title: "Container registry and secrets"
status: pending
priority: P1
dependencies: [1]
---

# Phase 2: Container Registry And Secrets

## Overview

Create the AWS image and secret foundation needed by every runtime. Output is ECR repositories, release-tag conventions, IAM roles, and secret references ready for App Runner/ECS.

## Requirements

- Functional: build and push API image; prepare optional Airflow/dashboard images; store runtime configuration securely.
- Non-functional: immutable image tags, least-privilege IAM, no plaintext secrets in git, repeatable local and CI commands.

## Architecture

```text
Developer or CI runner
  -> docker build
  -> aws ecr get-login-password
  -> docker push to ECR

AWS runtime
  -> App Runner/ECS access role
  -> ECR image pull
  -> Secrets Manager/SSM references injected as env vars
```

AWS App Runner can deploy from ECR source images. App Runner and ECS can reference Secrets Manager/SSM values instead of storing raw secret text in service config. Do not define `PORT` manually for App Runner; it is reserved and the existing Dockerfile already reads `${PORT:-8000}`.

## Related Code Files

- Modify/create later: `.github/workflows/deploy-aws.yml` - automated image build/push/deploy.
- Modify later: `.env.example` - add AWS-safe variable documentation only, no values.
- Modify later: `docs/aws-deployment.md` - operator runbook if deployment becomes maintained.
- Read: `Dockerfile` - root API image.
- Read: `src/airflow/Dockerfile` and `src/airflow/dashboard/Dockerfile` - optional images.

## Implementation Steps

1. Create ECR repositories:
   - `v-ota-api`
   - `v-ota-airflow` only if Phase 5 proceeds
   - `v-ota-dashboard` only if Phase 5 proceeds
2. Enable image scan-on-push if available in the selected account policy.
3. Define tags:
   - immutable release tag: git SHA
   - human alias: `dev-latest` or `prod-latest`
4. Create IAM roles:
   - CI deploy role, preferably assumed through GitHub OIDC.
   - App Runner ECR access role.
   - App Runner/ECS instance/task role for secret reads.
5. Move runtime values into Secrets Manager or SSM:
   - `OPENAI_API_KEY`
   - `DATABASE_URL`
   - `LANGCHAIN_API_KEY`
   - `LANGCHAIN_PROJECT`
   - `LANGCHAIN_TRACING_V2`
   - any Airflow Fernet/JWT/admin credentials if Phase 5 proceeds
6. Keep non-sensitive config as plain runtime env:
   - `APP_ENV=production`
   - `LOG_LEVEL=INFO`
   - `CORS_ORIGINS=<frontend or API docs origin>`
7. Document local push command for the first manual deployment:
   ```bash
   aws ecr get-login-password --region <region> \
     | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
   docker build -t v-ota-api:<git-sha> .
   docker tag v-ota-api:<git-sha> <account>.dkr.ecr.<region>.amazonaws.com/v-ota-api:<git-sha>
   docker push <account>.dkr.ecr.<region>.amazonaws.com/v-ota-api:<git-sha>
   ```

## Success Criteria

- [ ] ECR API repository exists and contains a git-SHA-tagged image.
- [ ] No `.env` or secret value is committed.
- [ ] App Runner/ECS roles can pull only the required ECR repos and read only required secrets.
- [ ] First image can be rebuilt from a clean checkout.
- [ ] Secret names/ARNs are documented in a redacted runbook.

## Risk Assessment

Main risk is leaking secrets through CI variables, copied `.env` files, or service logs. Mitigation: use OIDC for deploy auth, AWS secret references for sensitive values, and redacted documentation.
