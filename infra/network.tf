# --------------------------------------------------------------------------- #
# Networking: one VCN, one public subnet, ingress = SSH + the app port.
# Mirrors what the instance's current VCN (jobspy-vcn) has, so `terraform
# apply` reproduces the exact environment from zero.
# --------------------------------------------------------------------------- #
resource "oci_core_vcn" "vcn" {
  compartment_id = local.compartment_id
  display_name   = "jobspy-vcn"
  cidr_blocks    = ["10.0.0.0/16"]
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = "jobspy-igw"
  enabled        = true
}

resource "oci_core_route_table" "rt" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = "jobspy-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

resource "oci_core_subnet" "subnet" {
  compartment_id             = local.compartment_id
  vcn_id                     = oci_core_vcn.vcn.id
  display_name               = "jobspy-subnet"
  cidr_block                 = "10.0.1.0/24"
  route_table_id             = oci_core_route_table.rt.id
  security_list_ids          = [oci_core_security_list.app.id]
  prohibit_public_ip_on_vnic = false
}

resource "oci_core_security_list" "app" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = "jobspy-sl"

  egress_security_rules {
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
    protocol         = "all"
  }

  ingress_security_rules {
    protocol = "1" # ICMP (path MTU / ping)
    source   = "0.0.0.0/0"
  }
  ingress_security_rules {
    protocol    = "6" # TCP
    source      = "0.0.0.0/0"
    tcp_options {
      min = 22
      max = 22
    }
  }
  ingress_security_rules {
    protocol    = "6"
    source      = "0.0.0.0/0"
    tcp_options {
      min = var.app_port
      max = var.app_port
    }
  }
}
