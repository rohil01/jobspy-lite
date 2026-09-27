# --------------------------------------------------------------------------- #
# Who/where — from your OCI console (Profile → User settings → API keys)
# Feed these via terraform.tfvars (gitignored) or CI secrets / env vars.
# --------------------------------------------------------------------------- #
variable "tenancy_ocid" {
  type        = string
  description = "Tenancy OCID (ocid1.tenancy.oc1..…)"
}

variable "user_ocid" {
  type        = string
  description = "IAM user OCID that owns the API key"
}

variable "fingerprint" {
  type        = string
  description = "MD5 fingerprint of the API signing key"
}

variable "private_key" {
  type        = string
  sensitive   = true
  description = "PEM body of the API signing key (not the path)"
}

variable "region" {
  type        = string
  description = "OCI region identifier, e.g. us-ashburn-1"
}

# --------------------------------------------------------------------------- #
# What to build
# --------------------------------------------------------------------------- #
variable "compartment_ocid" {
  type        = string
  description = "Compartment for all resources. Empty = use the tenancy root."
  default     = ""
}

variable "availability_domain" {
  type        = number
  description = "Index (1-based) of the availability domain to launch in."
  default     = 1
}

variable "instance_shape" {
  type        = string
  description = "Shape. E2.1.Micro is Always Free; A1.Flex needs ocpus/memory set."
  default     = "VM.E2.1.Micro"
}

variable "a1_ocpus" {
  type    = number
  default = 2
}

variable "a1_memory_gb" {
  type    = number
  default = 12
}

variable "ssh_public_key" {
  type        = string
  description = "OpenSSH public key authorized on the instance."
}

variable "app_port" {
  type    = number
  default = 8000
}

variable "image_os" {
  type    = string
  default = "Canonical Ubuntu"
}

variable "image_os_version" {
  type    = string
  default = "22.04"
}

locals {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  # E2.1.Micro ignores ocpu/memory args; A1.Flex needs them.
  is_flex  = replace(var.instance_shape, "A1.Flex", "") != var.instance_shape
  shape_args = local.is_flex ? {
    ocpus = var.a1_ocpus
    memory_in_gbs = var.a1_memory_gb
  } : {}
}
