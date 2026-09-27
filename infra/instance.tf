# --------------------------------------------------------------------------- #
# Compute: Ubuntu instance, booted with the repo's cloud-init (Docker, swap,
# iptables for the app port). Same shape/config as the manual instance.
# --------------------------------------------------------------------------- #
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu" {
  count            = var.image_ocid != "" ? 0 : 1
  compartment_id   = local.compartment_id
  operating_system = var.image_os
  shape            = var.instance_shape
  sort_by          = "TIMECREATED"
  sort_order       = "DESC"
}

locals {
  # image_ocid is the reliable path (the images data source can return null
  # in some regions); falls back to the data source only when unset.
  image_id = var.image_ocid != "" ? var.image_ocid : try(data.oci_core_images.ubuntu[0].images[0].id, null)
}

resource "oci_core_instance" "app" {
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.availability_domain - 1].name
  compartment_id      = local.compartment_id
  display_name        = "jobspy-lite"

  shape = var.instance_shape

  dynamic "shape_config" {
    for_each = local.is_flex ? [1] : []
    content {
      ocpus         = var.a1_ocpus
      memory_in_gbs = var.a1_memory_gb
    }
  }

  source_details {
    source_type             = "image"
    source_id               = local.image_id
    boot_volume_size_in_gbs = 50
  }

  lifecycle {
    precondition {
      condition     = local.image_id != null
      error_message = "No image resolved: set the image_ocid variable (secret TF_VAR_IMAGE_OCID) to a valid Ubuntu image OCID."
    }
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.subnet.id
    assign_public_ip = true
    display_name     = "jobspy-lite-vnic"
    # No hostname_label: the subnet was created without a DNS label, and
    # combining the two makes LaunchInstance fail with NotAuthorizedOrNotFound.
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(file("${path.module}/../deploy/cloud-init.yaml"))
  }

  # agent_config omitted: defaults are fine, and the explicit block was a
  # suspect in the LaunchInstance 404 investigation.

  freeform_tags = {
    project = "jobspy-lite"
    managed = "terraform"
  }
}

output "instance_ocid" {
  value = oci_core_instance.app.id
}

output "public_ip" {
  value = oci_core_instance.app.public_ip
}
