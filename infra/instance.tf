# --------------------------------------------------------------------------- #
# Compute: Ubuntu instance, booted with the repo's cloud-init (Docker, swap,
# iptables for the app port). Same shape/config as the manual instance.
# --------------------------------------------------------------------------- #
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu" {
  compartment_id   = local.compartment_id
  operating_system = var.image_os
  shape            = var.instance_shape
  sort_by          = "TIMECREATED"
  sort_order       = "DESC"
}

locals {
  # Latest Ubuntu image compatible with the shape; override with image_ocid
  # to pin an exact build (e.g. ocid1.image.oc1.ap-hyderabad-1.aaaa…).
  image_id = var.image_ocid != "" ? var.image_ocid : data.oci_core_images.ubuntu.images[0].id
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

  create_vnic_details {
    subnet_id        = oci_core_subnet.subnet.id
    assign_public_ip = true
    display_name     = "jobspy-lite-vnic"
    hostname_label   = "jobspy-lite"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(file("${path.module}/../deploy/cloud-init.yaml"))
  }

  # E2.1.Micro cannot be stopped from inside the OS reliably; allow OCI to
  # force-reboot it during maintenance. Harmless for the Flex shapes.
  agent_config {
    are_all_plugins_disabled = false
    is_management_disabled   = false
    is_monitoring_disabled   = false
  }

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
