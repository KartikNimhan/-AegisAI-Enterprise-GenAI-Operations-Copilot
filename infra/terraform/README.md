# Terraform — not implemented

This directory is an intentional placeholder. No Terraform configuration
exists here, and none of it is deployable.

This project has not made a cloud-provider decision — see
[ADR 012](../../docs/architecture/decisions/012-deployment-architecture.md)
— so there is no managed-database/cache, networking, or IAM
infrastructure-as-code to write yet. The existing
[`infra/kubernetes/`](../kubernetes/) manifests assume a cluster already
exists (self-provisioned or managed); provisioning that cluster itself
(and any cloud-specific resources around it) is the scope a real
Terraform setup here would eventually cover, once a provider is chosen.

Do not treat the presence of this directory as evidence that a Terraform
deployment path exists or has been tested.
