# Terraform + Oracle Cloud provider pins.
# State: keep local (gitignored). For team use, plug in an OCI bucket backend:
#   backend "s3" { bucket = "jobspy-tfstate" ... }  # OCI object storage is S3-compatible

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

provider "oci" {
  tenancy_ocid = var.tenancy_ocid
  user_ocid    = var.user_ocid
  fingerprint  = var.fingerprint
  private_key  = var.private_key
  region       = var.region
}
