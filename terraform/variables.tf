variable "aws_region" {
  type        = string
  description = "Target AWS region for deploying TicketDesk infrastructure."
  default     = "ap-south-1"
}

variable "project_name" {
  type        = string
  description = "Identifier name for the project used in resource naming and tags."
  default     = "ticketdesk"
}

variable "environment" {
  type        = string
  description = "Deployment environment tier (e.g., poc, dev, staging, prod)."
  default     = "poc"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block allocation for the custom Virtual Private Cloud."
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  type        = string
  description = "CIDR block for the single public subnet hosting the EC2 web server."
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for the private subnets hosting the RDS PostgreSQL instance."
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "availability_zones" {
  type        = list(string)
  description = "List of distinct Availability Zones in the chosen region."
  default     = ["ap-south-1a", "ap-south-1b"]
}

variable "http_port" {
  type        = number
  description = "Internal HTTP port on which Nginx listens (destination for SSM port forwarding)."
  default     = 80
}

variable "app_port" {
  type        = number
  description = "Port on which the FastAPI application runs on loopback (uvicorn 127.0.0.1:8000)."
  default     = 8000
}

variable "ssh_port" {
  type        = number
  description = "Port designated for SSH administrative access."
  default     = 22
}

variable "db_port" {
  type        = number
  description = "Database port for Amazon RDS PostgreSQL."
  default     = 5432
}

variable "allowed_ssh_cidr" {
  type        = string
  description = "Trusted CIDR block permitted for SSH access. Must be an explicit IP or CIDR (e.g., '203.0.113.50/32'). Must not be '0.0.0.0/0'."
  default     = null

  validation {
    condition     = var.allowed_ssh_cidr == null || var.allowed_ssh_cidr != "0.0.0.0/0"
    error_message = "SSH ingress from 0.0.0.0/0 is strictly prohibited by security policy."
  }
}

# ==============================================================================
# Database Variables (Amazon RDS PostgreSQL)
# ==============================================================================
variable "db_name" {
  type        = string
  description = "Name of the initial PostgreSQL database created on RDS."
  default     = "ticketdesk"
}

variable "db_username" {
  type        = string
  description = "Master administrative username for Amazon RDS PostgreSQL."
  default     = "ticketdesk_admin"
}

variable "db_password" {
  type        = string
  description = "Master administrative password for Amazon RDS PostgreSQL."
  sensitive   = true
}

variable "db_instance_class" {
  type        = string
  description = "Compute and memory capacity of the RDS DB instance (Free Tier eligible: db.t3.micro or db.t4g.micro)."
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  type        = number
  description = "Allocated storage size in gigabytes (minimum 20 GB for general-purpose SSD gp3)."
  default     = 20
}

variable "db_engine_version" {
  type        = string
  description = "Major and minor engine version for Amazon RDS PostgreSQL."
  default     = "15.7"
}

# ==============================================================================
# Compute Variables (Amazon EC2 Application Server)
# ==============================================================================
variable "ec2_instance_type" {
  type        = string
  description = "EC2 compute instance type for the TicketDesk application server (Free Tier eligible: t3.micro or t2.micro)."
  default     = "t3.micro"
}

variable "ec2_key_name" {
  type        = string
  description = "Optional name of an existing EC2 Key Pair for SSH access. Defaults to null (SSM Session Manager preferred)."
  default     = null
}

variable "ec2_root_volume_size" {
  type        = number
  description = "Size of the root EBS volume in gigabytes (within AWS 30 GB free tier allowance)."
  default     = 20
}



